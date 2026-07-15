"""Les 16 faits contractuels, regroupés en familles qui partagent leurs sources.

Donnée pure : une famille = une recherche Tavily + une extraction LLM. Les
`keywords` ne servent qu'à découper une évidence trop longue pour le prompt
(cf. arp._select_evidence_text) — ils ne décident de rien.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactField:
    name: str
    allowed_values: tuple[str, ...]
    hint: str


@dataclass(frozen=True)
class FactFamily:
    name: str
    query: str
    fields: tuple[FactField, ...]
    keywords: tuple[str, ...]


FACT_FAMILIES: tuple[FactFamily, ...] = (
    FactFamily(
        name="entrainement_reutilisation",
        query=(
            "{tool} {vendor} terms customer content prompts used to train models "
            "opt out reuse confidentiality human review"
        ),
        fields=(
            FactField(
                name="trains_on_input",
                allowed_values=("yes", "no", "opt_out_available", "unknown"),
                hint=(
                    "opt_out_available quand le contenu soumis sert à l'entraînement "
                    "par défaut mais qu'un contrôle de retrait est explicitement offert."
                ),
            ),
            FactField(
                name="reentraining_opt_out",
                allowed_values=("yes", "no", "unknown"),
                hint="yes seulement si un mécanisme empêche le réentraînement sur les entrées et sorties.",
            ),
            FactField(
                name="contract_prohibits_reuse",
                allowed_values=("yes", "no", "unknown"),
                hint="yes seulement si le contrat interdit explicitement la réutilisation des données soumises.",
            ),
            FactField(
                name="human_review",
                allowed_values=("yes", "no", "unknown"),
                hint="yes si le fournisseur peut faire réviser manuellement les données soumises.",
            ),
        ),
        keywords=(
            r"train(?:ing)?|model performance|opt[ -]?out|do not train",
            r"human review|manual review|abuse monitoring|safety review|authorized personnel",
            r"confidential|reuse|disclosure|data sharing",
        ),
    ),
    FactFamily(
        name="hebergement_retention",
        query=(
            "{tool} {vendor} privacy data retention deletion residency hosting region "
            "subprocessors service providers"
        ),
        fields=(
            FactField(
                name="data_retention",
                allowed_values=("none", "limited", "indefinite", "unknown"),
                hint=(
                    "limited quand la rétention existe mais est bornée ou réductible ; "
                    "indefinite seulement en l'absence de toute limite de suppression."
                ),
            ),
            FactField(
                name="data_residency",
                allowed_values=("canada", "us", "eu", "other", "unknown"),
                hint="où les données soumises sont hébergées ou traitées.",
            ),
            FactField(
                name="sub_processors",
                allowed_values=("disclosed", "undisclosed", "unknown"),
                hint="disclosed seulement si la liste des sous-traitants est contractuellement divulguée.",
            ),
            FactField(
                name="foreign_vendor_dependency",
                allowed_values=("yes", "no", "unknown"),
                hint="yes si l'usage crée une dépendance envers un fournisseur étranger.",
            ),
        ),
        keywords=(
            r"data retention|retention|retain|deleted?.{0,80}30 days|within 30 days",
            r"servers located|various jurisdictions|United States|residen|region|hosting",
            r"sub[- ]?processors?|service providers?|vendors?",
        ),
    ),
    FactFamily(
        name="securite_technique",
        query=(
            "{tool} {vendor} security encryption in transit at rest SSO SAML MFA "
            "audit logs incident response breach notification trust center"
        ),
        fields=(
            FactField(
                name="encryption_standard",
                allowed_values=("strong", "partial", "none", "unknown"),
                hint=(
                    "strong seulement si le chiffrement en transit ET au repos sont "
                    "explicites ; partial si un seul l'est."
                ),
            ),
            FactField(
                name="authentication_support",
                allowed_values=("sso_mfa", "partial", "none", "unknown"),
                hint=(
                    "sso_mfa seulement si SSO ou SAML/OIDC ET MFA sont explicites ; "
                    "partial si un seul l'est."
                ),
            ),
            FactField(
                name="audit_logging",
                allowed_values=("prompt_output_accessible", "access_logs_only", "none", "unknown"),
                hint=(
                    "prompt_output_accessible seulement si l'auditabilité des prompts et "
                    "sorties est explicite et accessible à l'organisation ; access_logs_only "
                    "si seuls les journaux de connexion/admin sont explicites."
                ),
            ),
            FactField(
                name="incident_response",
                allowed_values=("documented_with_notice", "documented_no_notice", "none", "unknown"),
                hint=(
                    "documented_with_notice seulement si un processus de réponse aux "
                    "incidents ET un délai de notification sont documentés."
                ),
            ),
        ),
        keywords=(
            r"encrypt|encryption|tls|aes",
            r"sso|single sign-on|saml|oidc|mfa|multi-factor|identity provider",
            r"audit logs?|access logs?|prompt logs?|output logs?|admin console|organization logs?",
            r"incident response|security incident|breach notification|notify.{0,80}(hours|days)|sla",
        ),
    ),
    FactFamily(
        name="legal_pi",
        query=(
            "{tool} {vendor} terms of service governing law jurisdiction ownership "
            "output generated content intellectual property"
        ),
        fields=(
            FactField(
                name="ip_ownership",
                allowed_values=("customer", "vendor", "unclear", "unknown"),
                hint="qui détient le contenu généré et les droits sur le contenu soumis.",
            ),
            FactField(
                name="applicable_law",
                allowed_values=("quebec_canada", "foreign", "unknown"),
                hint="foreign quand le droit applicable est hors Québec/Canada.",
            ),
        ),
        keywords=(
            r"ownership|intellectual property|assign|right, title",
            r"governing law|California law|jurisdiction",
        ),
    ),
    FactFamily(
        name="termes_institutionnels",
        query=(
            "{tool} {vendor} enterprise institutional education higher education "
            "public sector license acceptable use DPA terms"
        ),
        fields=(
            FactField(
                name="institutional_terms",
                allowed_values=("acceptable", "problematic", "unknown"),
                hint=(
                    "problematic si une clause bloque ou restreint matériellement l'usage "
                    "institutionnel ; sinon unknown sauf acceptabilité explicite."
                ),
            ),
            FactField(
                name="quebec_higher_ed_license",
                allowed_values=("yes", "no", "unknown"),
                hint=(
                    "yes seulement si l'usage éducatif, entreprise, secteur public ou "
                    "institutionnel est explicitement permis."
                ),
            ),
        ),
        keywords=(
            r"institutional use|enterprise terms|education|higher education|public sector|acceptable use",
            r"license|licence|government|public sector|education institution|academic",
        ),
    ),
)

ALL_FACT_FIELDS: tuple[FactField, ...] = tuple(
    field for family in FACT_FAMILIES for field in family.fields
)


def family_by_name(name: str) -> FactFamily | None:
    for family in FACT_FAMILIES:
        if family.name == name:
            return family
    return None
