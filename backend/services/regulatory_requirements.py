"""Regulation discovery and the normalized requirement model (W9G).

THE REGULATION API IS THE REQUIREMENT AUTHORITY. Ireland's current nine EndUser
fields are an OUTPUT of this module, never an input to it. Twilio's Regulatory
Compliance API is public beta and its requirements can change, so the engine asks
the provider what is required and adapts, rather than shipping a frozen field list.
W9G re-verified that IE/local/business still returns exactly one regulation with the
same nine fields and one business_address document -- and that verification is a
fact about today, not a licence to hardcode.

WHAT THE ADAPTER IS FOR. Twilio's response nests requirements three deep with
provider-specific key names. Letting that shape leak into routes and UI would mean
every consumer breaks when the provider reshapes a payload. The normalized model
below is what the rest of the application sees.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── outcomes, distinguished (W9F's three-state discipline) ─────────────────
OK = "ok"
NOT_FOUND = "regulation_not_found"
AMBIGUOUS = "regulation_ambiguous"
UNAVAILABLE = "regulation_provider_unavailable"


@dataclass(frozen=True)
class FieldRequirement:
    """One field the provider wants, in our vocabulary."""
    name: str                                  # provider machine_name
    label: str = ""                            # provider friendly_name
    description: str = ""                      # provider guidance, verbatim
    required: bool = True
    options: tuple[str, ...] = ()              # parsed enum, when the provider states one
    constraint: str = ""

    @property
    def is_enum(self) -> bool:
        return bool(self.options)


@dataclass(frozen=True)
class DocumentRequirement:
    """One supporting document the provider wants."""
    requirement_name: str
    name: str
    accepted_type: str                         # e.g. 'business_address'
    fields: tuple[FieldRequirement, ...] = ()
    description: str = ""
    required: bool = True

    @property
    def satisfied_by_address_sids(self) -> bool:
        """True when the document is satisfied by referencing Twilio Address SIDs
        rather than by uploading a file. Ireland's proof of address is this kind.
        Anything else needs document storage the platform does not have -- see
        regulatory_engine.UNSUPPORTED_DOCUMENT_REQUIREMENT."""
        return [f.name for f in self.fields] == ["address_sids"]


@dataclass(frozen=True)
class RegulationRequirementSet:
    regulation_sid: str
    friendly_name: str
    iso_country: str
    number_type: str
    end_user_type: str
    end_user_requirement_name: str = ""
    end_user_fields: tuple[FieldRequirement, ...] = ()
    documents: tuple[DocumentRequirement, ...] = ()

    @property
    def end_user_field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.end_user_fields)

    def fingerprint(self) -> str:
        """A stable identity for "the requirements as we understood them".

        Stored on the profile so a drift check before submission can tell whether
        the provider changed the shape under us -- the regulation SID alone is not
        enough, because Twilio can alter a regulation's fields without reissuing it.
        """
        import hashlib
        parts = [self.regulation_sid, self.iso_country, self.number_type,
                 self.end_user_type, "|".join(self.end_user_field_names),
                 "|".join(f"{d.accepted_type}:{','.join(x.name for x in d.fields)}"
                          for d in self.documents)]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    requirements: RegulationRequirementSet | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


_ENUM = re.compile(r"\[([^\]]+)\]")


def _parse_options(description: str) -> tuple[str, ...]:
    """Pull an enum out of the provider's prose.

    Twilio states allowed values inside square brackets in the field description
    ("Choose any one of the following values: [DIRECT_CUSTOMER, ...]"). Parsing
    prose is fragile, so a failure to parse yields NO options rather than a wrong
    one: a field with no options is treated as free text, which is the safe default.
    """
    m = _ENUM.search(str(description or ""))
    if not m:
        return ()
    vals = [v.strip() for v in m.group(1).split(",")]
    vals = [v for v in vals if v and " " not in v]
    return tuple(vals) if len(vals) >= 2 else ()


#: Fields the provider marks optional in its own description text.
def _is_optional(name: str, description: str) -> bool:
    return "optional" in str(description or "").lower() or name == "comments"


def normalize_regulation(reg) -> RegulationRequirementSet:
    """Twilio Regulation instance -> our model. Tolerant of extra provider keys.

    A field or document type the provider adds later flows straight through as a
    requirement; nothing is filtered against an allow-list, because filtering would
    silently drop a new regulatory obligation.
    """
    requirements = getattr(reg, "requirements", None) or {}
    eu_groups = requirements.get("end_user") or []
    eu = eu_groups[0] if eu_groups else {}
    fields: list[FieldRequirement] = []
    detailed = eu.get("detailed_fields") or []
    by_name = {d.get("machine_name"): d for d in detailed}
    for name in (eu.get("fields") or []):
        d = by_name.get(name, {})
        desc = str(d.get("description") or "")
        fields.append(FieldRequirement(
            name=name, label=str(d.get("friendly_name") or ""), description=desc,
            required=not _is_optional(name, desc), options=_parse_options(desc),
            constraint=str(d.get("constraint") or "")))

    docs: list[DocumentRequirement] = []
    for group in (requirements.get("supporting_document") or []):
        for item in (group or []):
            for accepted in (item.get("accepted_documents") or []):
                dfields = []
                dby = {x.get("machine_name"): x for x in (accepted.get("detailed_fields") or [])}
                for fname in (accepted.get("fields") or []):
                    dd = dby.get(fname, {})
                    dfields.append(FieldRequirement(
                        name=fname, label=str(dd.get("friendly_name") or ""),
                        description=str(dd.get("description") or ""),
                        constraint=str(dd.get("constraint") or "")))
                docs.append(DocumentRequirement(
                    requirement_name=str(item.get("requirement_name") or ""),
                    name=str(item.get("name") or ""),
                    accepted_type=str(accepted.get("type") or ""),
                    fields=tuple(dfields),
                    description=str(item.get("description") or "")))

    return RegulationRequirementSet(
        regulation_sid=str(getattr(reg, "sid", "")),
        friendly_name=str(getattr(reg, "friendly_name", "")),
        iso_country=str(getattr(reg, "iso_country", "")).upper(),
        number_type=str(getattr(reg, "number_type", "")),
        end_user_type=str(getattr(reg, "end_user_type", "")),
        end_user_requirement_name=str(eu.get("requirement_name") or ""),
        end_user_fields=tuple(fields), documents=tuple(docs))


async def discover_regulation(*, iso_country: str, number_type: str,
                              end_user_type: str, client=None) -> DiscoveryResult:
    """Ask the provider what is required. NO DATABASE WRITES.

    `client` is the Twilio client to use. Regulations are provider-global (not
    account-scoped), so the parent client is correct and cheapest; a tenant client
    would work identically.
    """
    country = str(iso_country or "").strip().upper()
    if not country:
        return DiscoveryResult(status=NOT_FOUND, detail="no_iso_country")
    if client is None:
        from services import telephony
        try:
            client = telephony._master_client()
        except Exception as e:
            return DiscoveryResult(status=UNAVAILABLE,
                                   detail=type(e).__name__)
    try:
        regs = client.numbers.v2.regulatory_compliance.regulations.list(
            iso_country=country, number_type=number_type,
            end_user_type=end_user_type, limit=20)
    except Exception as e:
        # A provider outage is NOT "no such regulation". Collapsing the two would
        # tell a customer their country is unsupported because Twilio had a bad
        # minute.
        from services.telephony import _safe_provider_error
        logger.error("Regulation discovery failed for %s/%s/%s: %s",
                     country, number_type, end_user_type, type(e).__name__)
        return DiscoveryResult(status=UNAVAILABLE, detail=_safe_provider_error(e))

    if not regs:
        return DiscoveryResult(status=NOT_FOUND,
                               detail=f"{country}/{number_type}/{end_user_type}")
    if len(regs) > 1:
        # Never pick one. Which regulation applies is a compliance decision.
        return DiscoveryResult(
            status=AMBIGUOUS,
            detail=f"{len(regs)} regulations: {[getattr(r, 'sid', '?') for r in regs]}")
    return DiscoveryResult(status=OK, requirements=normalize_regulation(regs[0]))
