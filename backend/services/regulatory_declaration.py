"""The provider declaration policy (W9G.3).

── WHAT THIS SETTLES ──────────────────────────────────────────────────────────
`business_identity` and `is_subassigned` are the two EndUser fields the Ireland
Local/Business regulation requires that are NOT facts about the customer's
business. They are a statement about the commercial relationship, in Twilio's own
terminology, and W9C/W9G/W9G.1 could not establish from Twilio's documentation
which actor they describe. The engine refused to guess and blocked submission.

Twilio Support has now answered for this exact architecture:

    OpenLines owns the parent account and is an ISV. Each SMB customer gets its own
    subaccount. The Irish number and all regulatory resources live in that
    subaccount. The SMB customer is the business that receives and uses the number.

    -> The SMB customer is the correct EndUser (for DANI: DANI, not OpenLines).
    -> business_identity = DIRECT_CUSTOMER   (describes the SMB customer)
    -> is_subassigned    = NO                (also describes the SMB customer: the
                                              number is assigned to the EndUser the
                                              Bundle represents and is not being
                                              further subassigned BY that EndUser)
    -> No separate OpenLines ISV identity is required inside the customer's Bundle.
    -> The subaccount architecture does not change the answer.

Separately, Twilio said OpenLines' PARENT-ACCOUNT primary business profile should be
classified ISV/Reseller. That is Trust Hub, not this Bundle, and is not touched here.

── WHY THIS IS A TABLE AND NOT A CONSTANT ─────────────────────────────────────
The answer is specific to (Twilio, IE, local, business, our ISV-subaccount
architecture). It is NOT a general truth about regulatory bundles: a different
country, number type, end-user type, or a future architecture where OpenLines holds
the number itself could all invert it. So the mapping is keyed on the full context
and there is deliberately NO fallback, NO wildcard and NO default. An unrecognised
context resolves to nothing and the caller fails closed -- which is the same posture
the engine had before the answer arrived, just narrowed to the contexts Twilio has
actually spoken about.

── AND IT IS STILL SUBORDINATE TO THE LIVE REGULATION ─────────────────────────
This policy says what we BELIEVE the answer is. The Regulation API says what the
provider currently ACCEPTS. `validate_against_regulation()` is what reconciles them,
and if Twilio ever stops recognising these fields or stops accepting these values,
the policy is refused rather than submitted -- a support answer from today is not
licence to file against a regulation that has since changed.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The architecture Twilio was asked about: OpenLines as ISV, one subaccount per
#: customer, the number and regulatory resources inside the customer's subaccount.
ARCHITECTURE_ISV_CUSTOMER_SUBACCOUNT = "openlines_isv_customer_subaccount"

#: Who the declaration describes. Recorded so the reasoning survives the next reader.
SUBJECT_TENANT_END_USER = "tenant_end_user"

RESOLVED = "resolved"
UNRESOLVED = "declaration_policy_unresolved"
FIELD_NOT_REQUIRED = "not_required_by_regulation"
VALUE_REJECTED = "value_not_accepted_by_regulation"


@dataclass(frozen=True)
class DeclarationPolicy:
    provider: str
    iso_country: str
    number_type: str
    end_user_type: str
    architecture: str
    business_identity: str
    is_subassigned: str
    subject: str
    source: str

    def as_attributes(self) -> dict:
        return {"business_identity": self.business_identity,
                "is_subassigned": self.is_subassigned}


#: EXACT-MATCH ONLY. Every key component must match; nothing is inherited.
_POLICIES: dict[tuple[str, str, str, str, str], DeclarationPolicy] = {
    ("twilio", "IE", "local", "business", ARCHITECTURE_ISV_CUSTOMER_SUBACCOUNT):
        DeclarationPolicy(
            provider="twilio", iso_country="IE", number_type="local",
            end_user_type="business",
            architecture=ARCHITECTURE_ISV_CUSTOMER_SUBACCOUNT,
            business_identity="DIRECT_CUSTOMER",
            is_subassigned="NO",
            subject=SUBJECT_TENANT_END_USER,
            source="twilio_support_confirmation_ie_local_business"),
}

#: The fields this policy answers. Used to check the live regulation still asks for
#: them before anything is submitted.
POLICY_FIELDS = ("business_identity", "is_subassigned")


def resolve(*, provider: str = "twilio", iso_country: str, number_type: str,
            end_user_type: str,
            architecture: str = ARCHITECTURE_ISV_CUSTOMER_SUBACCOUNT
            ) -> DeclarationPolicy | None:
    """The confirmed declaration for this exact context, or None.

    None means "Twilio has not told us the answer for this combination" -- never
    "use a sensible default". The caller must fail closed.
    """
    key = (str(provider or "").strip().lower(),
           str(iso_country or "").strip().upper(),
           str(number_type or "").strip().lower(),
           str(end_user_type or "").strip().lower(),
           str(architecture or "").strip())
    return _POLICIES.get(key)


def validate_against_regulation(policy: DeclarationPolicy, requirements) -> tuple[str, str]:
    """Does the CURRENT regulation still ask for these fields and accept these values?

    Returns (status, detail). RESOLVED only when every field the policy answers is
    still required by the regulation AND the value is among the options the provider
    currently states. A field the regulation has stopped asking for is fine to omit,
    but a field it still asks for whose value it no longer accepts is a hard stop:
    submitting it would file a value the provider has rejected.
    """
    by_name = {f.name: f for f in requirements.end_user_fields}
    values = policy.as_attributes()
    for name in POLICY_FIELDS:
        field = by_name.get(name)
        if field is None:
            # The regulation no longer asks for it. Nothing to declare, and nothing
            # to fail on -- the value simply will not be sent.
            continue
        value = values[name]
        if field.is_enum and value not in field.options:
            return (VALUE_REJECTED,
                    f"{name}={value} not in {list(field.options)}")
    return RESOLVED, ""


def applicable_attributes(policy: DeclarationPolicy, requirements) -> dict:
    """Only the declaration values the current regulation actually asks for.

    Sending a field the regulation has dropped would be submitting a statement it no
    longer defines.
    """
    asked = set(requirements.end_user_field_names)
    return {k: v for k, v in policy.as_attributes().items() if k in asked}
