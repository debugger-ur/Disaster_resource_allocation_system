/** Small bits of workflow knowledge shared by the public and admin bundles. */

export const CATEGORY_LABELS = {
  hospital: "Hospital",
  relief_camp: "Relief camp",
  food_water: "Food & water distribution",
  rescue_team: "Rescue team",
  warehouse: "Warehouse",
  shelter: "Shelter",
  medical_camp: "Medical camp",
  other: "Other help centre",
};

export const presetOrigin = {
  latitude: 30.3165,
  longitude: 78.0322,
  label: "Dehradun city centre",
};

const STEPS = [
  { key: "submitted", label: "Submitted", note: "Request received with a tracking ID." },
  { key: "verification", label: "Automated verification", note: "Duplicate and risk checks run server-side." },
  { key: "awaiting_approval", label: "Coordinator review", note: "A person approves, rejects or asks for more detail." },
  { key: "approved", label: "Approved", note: "Eligible for resource allocation." },
  { key: "resources_assigned", label: "Resources assigned", note: "Stock committed from a help centre." },
  { key: "in_progress", label: "In progress", note: "Dispatch and delivery under way." },
  { key: "resolved", label: "Resolved", note: "Response complete." },
];

const STATUS_INDEX = {
  submitted: 0,
  under_verification: 1,
  possible_duplicate: 1,
  awaiting_approval: 2,
  approved: 3,
  resources_assigned: 4,
  in_progress: 5,
  resolved: 6,
};

/**
 * The status timeline for a request. `possible_duplicate` is a flavour of the
 * verification step; `rejected` is a terminal step added after it.
 */
export function buildTrackSteps(status) {
  const currentIndex = STATUS_INDEX[status] ?? 0;
  const steps = STEPS.map((step, index) => ({
    index: index + 1,
    label: step.label,
    note: step.note,
    state: index < currentIndex ? "done" : index === currentIndex ? "current" : "pending",
  }));

  if (status === "possible_duplicate") {
    steps[1].note = "A similar recent report was found. A coordinator is deciding whether to merge, link or keep both.";
  }
  if (status === "under_verification") {
    steps[1].note = "Some details need human verification before a decision. The report has not been rejected.";
  }
  if (status === "rejected") {
    return [
      { ...steps[0], state: "done" },
      { ...steps[1], state: "done", note: "Verification completed; the report was reviewed by a person." },
      { index: 3, label: "Rejected", note: "Closed by a coordinator. The reason is shown above.", state: "current" },
    ];
  }
  return steps;
}
