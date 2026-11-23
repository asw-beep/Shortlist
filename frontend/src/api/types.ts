/** Short names for the API's shapes, all generated from the backend's OpenAPI schema. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RankedJob = Schemas["RankedJobOut"];
export type Feed = Schemas["FeedOut"];
export type SavedItem = Schemas["SavedItem"];
export type ProfileIn = Schemas["ProfileIn"];
export type ProfileOut = Schemas["ProfileOut"];
export type ProfileDraft = Schemas["ProfileDraft"];
export type SkillIn = Schemas["SkillIn"];
export type FeedbackKind = Schemas["FeedbackIn"]["kind"];
