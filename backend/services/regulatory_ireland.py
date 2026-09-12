"""Ireland Local/Business UX mapping, layered on the dynamic requirements (W9G).

This is presentation only. It maps whatever fields the Regulation API currently
returns onto labels and help text a business owner can answer, and it drops nothing
and invents nothing: a field the provider adds later appears with its provider label
until someone writes a friendlier one, and a field the provider removes simply stops
being asked for.

── THE ONE THING THIS MODULE REFUSES TO DECIDE ────────────────────────────────
`business_identity` and `is_subassigned` are a COMPLIANCE DECLARATION to an Irish
regulator about the commercial relationship between OpenLines and the customer. W9C
flagged the semantics as unresolved and W9G re-read Twilio's current documentation to
settle it. One half is now settled and the other is not.

SETTLED -- who the EndUser is. Twilio's REST walkthrough states: "The End-User is
the individual or business that answers the phone call or message." That is the
tenant, not OpenLines. It also agrees with Irish provider behaviour, which demands
proof of address in the NUMBER'S locality: OpenLines is Canadian and has no Irish
address, so only the tenant's identity can satisfy the requirement.

NOT SETTLED -- the two enum values. Twilio's field help says:

  business_identity: "Use 'DIRECT_CUSTOMER' if your business uses this phone number
      to communicate internally or with your customers. Use
      'INDEPENDENT_SOFTWARE_VENDOR' if your business uses this phone number in a
      product that you sell to your customers."
  is_subassigned:    "A sub assigned phone number is where Independent Software
      Vendor (ISV) assigns the phone number to their end customer. If you are a
      direct customer, answer NO."

Read as questions about the END USER (the tenant), the answers are DIRECT_CUSTOMER
and NO -- the tenant is nobody's reseller. Read as questions about the ARRANGEMENT,
OpenLines is an ISV sub-assigning a number to its customer, so is_subassigned is YES
-- but that contradicts the same sentence's own coupling of DIRECT_CUSTOMER with NO.
Twilio's ISV guidance covers A2P 10DLC messaging brands, not regulatory bundles, and
neither the Bundles nor the Regulations documentation states which reading applies.

So these two fields are marked UNRESOLVED_DECLARATION. The engine collects
everything else, validates the address, builds every provider resource and runs
Evaluation -- but submission is blocked with `unresolved_isv_declaration` until an
operator supplies the values explicitly. Guessing here would put a false statement
in front of a regulator to save one support ticket.
"""
from __future__ import annotations

from services.regulatory_requirements import RegulationRequirementSet

#: Fields whose value is a compliance declaration about the OpenLines/tenant
#: relationship rather than a fact the customer can simply be asked for.
#:
#: W9G.3: Twilio Support confirmed the values for (Twilio, IE, local, business,
#: OpenLines ISV + per-customer subaccount), so for THAT context they are now
#: system-sourced -- see services/regulatory_declaration.py. They remain listed here
#: because the list is what marks them as NOT the customer's to answer, which is
#: still true: the customer is authoritative for facts about their business, and
#: OpenLines is authoritative for mapping its own architecture into Twilio's
#: terminology. A context with no confirmed policy still fails closed.
UNRESOLVED_DECLARATION_FIELDS = ("business_identity", "is_subassigned")

#: Customer-facing labels and help. Keyed by provider machine_name. A field absent
#: from here still gets collected, using the provider's own label.
IE_FIELD_UX: dict[str, dict[str, str]] = {
    "business_name": {
        "label": "Registered business name",
        "help": "Exactly as registered with the Companies Registration Office.",
    },
    "business_website": {
        "label": "Business website",
        "help": "A public website for the business.",
    },
    "business_registration_number": {
        "label": "CRO registration number",
        "help": "Your Companies Registration Office number (e.g. 123456 or NC123456), "
                "a Registered Charity Number, or your full organisation name if you "
                "are a public sector body.",
    },
    "first_name": {
        "label": "Authorised representative — first name",
        "help": "A senior manager responsible for the phone numbers.",
    },
    "last_name": {
        "label": "Authorised representative — last name",
        "help": "A senior manager responsible for the phone numbers.",
    },
    "email": {
        "label": "Authorised representative — email",
        "help": "Regulatory updates about this number are sent here.",
    },
    "business_identity": {
        "label": "Business classification",
        "help": "Set by OpenLines from our provider relationship — you are not "
                "asked to interpret this.",
    },
    "is_subassigned": {
        "label": "Number assigned to an end customer",
        "help": "Set by OpenLines from our provider relationship — you are not "
                "asked to interpret this.",
    },
    "comments": {
        "label": "Additional comments",
        "help": "Optional. Anything else useful for vetting this application.",
    },
}

CUSTOMER_SUPPLIED = "customer"
OPERATOR_SUPPLIED = "operator"
UNRESOLVED = "unresolved_declaration"


def describe_fields(requirements: RegulationRequirementSet) -> list[dict]:
    """The field list a UI should render, in provider order.

    `source` says who answers: the customer, or an operator making a declaration.
    `resolved` is False only for the declaration fields whose semantics are still
    open -- a UI should surface that rather than silently pre-filling a guess.
    """
    out: list[dict] = []
    for f in requirements.end_user_fields:
        ux = IE_FIELD_UX.get(f.name, {})
        declaration = f.name in UNRESOLVED_DECLARATION_FIELDS
        out.append({
            "name": f.name,
            "label": ux.get("label") or f.label or f.name,
            "help": ux.get("help") or f.description,
            "required": f.required,
            "options": list(f.options),
            "source": OPERATOR_SUPPLIED if declaration else CUSTOMER_SUPPLIED,
            "resolved": not declaration,
            "state": UNRESOLVED if declaration else "collectable",
            # The provider's own words are always carried through, so a UI can show
            # them verbatim and nobody has to trust this module's paraphrase.
            "provider_label": f.label,
            "provider_description": f.description,
        })
    return out


def missing_fields(requirements: RegulationRequirementSet,
                   attributes: dict) -> list[str]:
    """Required provider fields with no value supplied. Provider order preserved."""
    have = {k for k, v in (attributes or {}).items()
            if str(v if v is not None else "").strip() != ""}
    return [f.name for f in requirements.end_user_fields if f.required and f.name not in have]


def invalid_enum_fields(requirements: RegulationRequirementSet,
                        attributes: dict) -> list[str]:
    """Supplied values that are not among the provider's stated options."""
    bad = []
    for f in requirements.end_user_fields:
        if not f.is_enum:
            continue
        val = str((attributes or {}).get(f.name) or "").strip()
        if val and val not in f.options:
            bad.append(f.name)
    return bad


def unresolved_declarations(requirements: RegulationRequirementSet,
                            attributes: dict) -> list[str]:
    """Declaration fields the regulation asks for that no operator has answered.

    Submission must block on these. They are not missing customer data -- they are a
    statement about OpenLines' relationship to the customer that nobody has yet
    established the correct wording for.
    """
    supplied = {k for k, v in (attributes or {}).items()
                if str(v if v is not None else "").strip() != ""}
    asked = set(requirements.end_user_field_names)
    return [n for n in UNRESOLVED_DECLARATION_FIELDS
            if n in asked and n not in supplied]
