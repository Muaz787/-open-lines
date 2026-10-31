// Plain wording for the reason codes from services/routing_engine.py. An unknown
// code falls back to neutral wording, so a new engine reason never shows raw.
const REASONS: Record<string, string> = {
  rule_match: 'A routing rule matched this call.',
  rule_fallback_destination: 'A routing rule matched, so the rule’s backup destination was used.',
  rule_matched_destination_unavailable: 'A routing rule matched, but its destinations weren’t available, so your fallback applies.',
  urgent_escalation: 'The call is urgent, so it goes to your urgent destination.',
  urgent_no_destination: 'The call is urgent, but no urgent destination is available, so your fallback applies.',
  default_destination: 'No rule matched, so your default destination was used.',
  low_confidence: 'The AI wasn’t confident enough to route this call, so your low-confidence setting applies.',
  public_emergency_no_dial: 'This sounds like a public emergency, so the AI handles it and nothing is dialed.',
}

export function routingReasonText(reason: string): string {
  if (REASONS[reason]) return REASONS[reason]
  if (reason.startsWith('no_match') || reason.startsWith('fallback')) {
    return 'No rule matched, so your fallback applies.'
  }
  return 'This is the result for the details you entered.'
}
