"""The search statement: hard filters, two retrievers fused with RRF, explained scores.

One `text()` statement with bound parameters. The only part that varies is the score
expression, picked from SCORE_EXPRESSIONS by variant (never built from user input).

Keyword retrieval ORs the query's lexemes instead of using websearch_to_tsquery's AND: the
feed query is "target roles + top skills", and almost no posting mentions all of them.
ts_rank_cd still ranks postings that match more lexemes higher.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import TextClause, bindparam, text

from app.catalog.models import EMBEDDING_DIM

REMOTE = "('remote_country', 'remote_global')"

# One role = one company, one title (any case), one place. The feed shows each role once, and a
# dismissal, an application or an exclusion applies to every posting of that role: a twin on
# another board, or a repost under a new id.
OTHER_COPY_OF_THIS_ROLE = """
    FROM postings p2
    JOIN boards b2 ON b2.id = p2.board_id
    JOIN posting_features f2 ON f2.posting_id = p2.id
    WHERE b2.company_id = b.company_id
      AND lower(p2.title) = lower(p.title)
      AND coalesce(f2.city, f2.remote_scope) = coalesce(f.city, f.remote_scope)
"""

WEIGHTED = (
    ":w_skill * f_skill + :w_rrf * f_rrf + :w_experience * f_experience"
    " + :w_location * f_location + :w_recency * f_recency + :w_personal * f_personal"
)

SCORE_EXPRESSIONS = {
    "fts": "kw_rank",
    "dense": "cosine",
    "hybrid": "f_rrf",
    "utility": WEIGHTED,  # called with w_personal = 0
    "full": WEIGHTED,
}

TEMPLATE = f"""
WITH me AS (
    SELECT coalesce(array_agg(skill_id), '{{}}') AS skill_ids
    FROM profile_skills WHERE user_id = :user_id
),
tsq AS (
    SELECT CASE WHEN count(*) = 0 THEN NULL
                ELSE string_agg(quote_literal(lexeme), ' | ')::tsquery END AS query
    FROM unnest(tsvector_to_array(to_tsvector('english', coalesce(CAST(:q AS text), ''))))
        AS lexeme
),
eligible AS (
    SELECT p.id, p.title, p.url, p.first_seen_at, p.embedding, p.search_tsv,
           b.company_id, c.name AS company, f.city, f.remote_scope, f.min_years,
           f.remote_scope IN {REMOTE} AS remote_eligible
    FROM postings p
    JOIN posting_features f ON f.posting_id = p.id
    JOIN boards b ON b.id = p.board_id
    JOIN companies c ON c.id = b.company_id
    WHERE p.status = 'open' AND f.relevant AND p.embedding IS NOT NULL
      -- a disabled board is no longer fetched, so its postings could never close
      AND b.enabled
      AND f.role_family = ANY(CAST(:roles AS text[]))
      AND (f.seniority = ANY(CAST(:seniority AS text[])) OR f.seniority = 'unknown')
      AND (
            (f.remote_scope IN {REMOTE} AND :remote_ok AND coalesce(f.country, 'IN') = 'IN')
         OR (f.remote_scope NOT IN {REMOTE} AND f.country = 'IN'
             AND (:relocate OR cardinality(CAST(:locations AS text[])) = 0
                  OR f.city IS NULL OR f.city = ANY(CAST(:locations AS text[]))))
      )
      AND NOT (lower(c.name) = ANY(CAST(:avoid AS text[]))
               OR c.slug = ANY(CAST(:avoid AS text[])))
      AND NOT EXISTS (
            SELECT 1 {OTHER_COPY_OF_THIS_ROLE}
              AND EXISTS (
                    SELECT 1 FROM interactions i
                    WHERE i.user_id = :user_id AND i.posting_id = p2.id
                      AND i.kind IN ('dismissed', 'applied')))
      AND (CAST(:since AS timestamptz) IS NULL OR p.first_seen_at > CAST(:since AS timestamptz))
      AND NOT EXISTS (
            SELECT 1 {OTHER_COPY_OF_THIS_ROLE}
              AND p2.id = ANY(CAST(:exclude AS uuid[])))
),
dense AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:qvec AS vector), id) AS rank
    FROM eligible
    ORDER BY embedding <=> CAST(:qvec AS vector), id
    LIMIT :candidates
),
kw AS (
    SELECT e.id, ts_rank_cd(e.search_tsv, tsq.query) AS kw_rank,
           row_number() OVER (ORDER BY ts_rank_cd(e.search_tsv, tsq.query) DESC, e.id) AS rank
    FROM eligible e CROSS JOIN tsq
    WHERE tsq.query IS NOT NULL AND e.search_tsv @@ tsq.query
    ORDER BY kw_rank DESC, e.id
    LIMIT :candidates
),
fused AS (
    SELECT coalesce(d.id, k.id) AS id,
           coalesce(1.0 / (:k + d.rank), 0) + coalesce(1.0 / (:k + k.rank), 0) AS rrf,
           coalesce(k.kw_rank, 0) AS kw_rank
    FROM dense d FULL OUTER JOIN kw k ON k.id = d.id
),
posting_skill_stats AS (
    SELECT ps.posting_id,
           count(*) FILTER (WHERE ps.kind = 'required') AS required_count,
           count(*) FILTER (WHERE ps.kind = 'required' AND ps.skill_id = ANY(me.skill_ids))
               AS matched_required,
           count(*) FILTER (WHERE ps.kind = 'nice' AND ps.skill_id = ANY(me.skill_ids))
               AS matched_nice,
           array_agg(s.name ORDER BY s.name) FILTER (WHERE ps.skill_id = ANY(me.skill_ids))
               AS matched,
           array_agg(s.name ORDER BY s.name)
               FILTER (WHERE ps.kind = 'required' AND NOT ps.skill_id = ANY(me.skill_ids))
               AS missing
    FROM posting_skills ps
    JOIN skills s ON s.id = ps.skill_id
    CROSS JOIN me
    WHERE ps.posting_id IN (SELECT id FROM fused)
    GROUP BY ps.posting_id
),
scored AS (
    SELECT e.id, e.title, e.company, e.company_id, e.url, e.city, e.remote_scope,
           e.first_seen_at, fu.kw_rank,
           1 - (e.embedding <=> CAST(:qvec AS vector)) AS cosine,
           least(1.0, (coalesce(st.matched_required, 0) + 0.5 * coalesce(st.matched_nice, 0))
                      / greatest(coalesce(st.required_count, 0), 1)) AS f_skill,
           fu.rrf / (2.0 / (:k + 1)) AS f_rrf,
           CASE WHEN e.min_years IS NULL THEN 1.0
                ELSE greatest(0, 1 - 0.5 * greatest(0, e.min_years - :years)) END AS f_experience,
           CASE WHEN e.remote_eligible OR e.city = ANY(CAST(:locations AS text[])) THEN 1.0
                ELSE 0.5 END AS f_location,
           exp(-greatest(0, extract(epoch FROM CAST(:now AS timestamptz) - e.first_seen_at))
               / 86400.0 / :recency_days) AS f_recency,
           CASE WHEN CAST(:taste AS vector) IS NULL THEN 0.0
                ELSE (1 - (e.embedding <=> CAST(:taste AS vector)) / 2)
                     * least(1.0, CAST(:feedback_count AS float) / :ramp) END AS f_personal,
           coalesce(st.matched, '{{}}') AS matched_skills,
           coalesce(st.missing, '{{}}') AS missing_skills
    FROM fused fu
    JOIN eligible e ON e.id = fu.id
    LEFT JOIN posting_skill_stats st ON st.posting_id = fu.id
),
ranked AS (
    SELECT *, {{score}} AS score FROM scored
),
deduped AS (
    SELECT DISTINCT ON (company_id, lower(title), coalesce(city, remote_scope)) *
    FROM ranked
    ORDER BY company_id, lower(title), coalesce(city, remote_scope), score DESC, id
)
SELECT id, title, company, url, city, remote_scope, first_seen_at, score,
       f_skill, f_rrf, f_experience, f_location, f_recency, f_personal,
       matched_skills, missing_skills
FROM deduped
ORDER BY score DESC, id
LIMIT :limit
"""

_STATEMENTS = {
    variant: text(TEMPLATE.replace("{score}", expression)).bindparams(
        bindparam("qvec", type_=Vector(EMBEDDING_DIM)),
        bindparam("taste", type_=Vector(EMBEDDING_DIM)),
    )
    for variant, expression in SCORE_EXPRESSIONS.items()
}


def search_statement(variant: str) -> TextClause:
    return _STATEMENTS[variant]
