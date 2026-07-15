# Fetcher Tavily — preuve par champ, dégradation gracieuse, coût maîtrisé

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre chaque fait contractuel extrait par le fetcher Tavily vérifiable (URL + citation verbatim), incapable de faire planter `Interview.assess`, et deux fois moins cher en recherches.

**Architecture :** Les 16 champs de `ContractFacts` sont regroupés en 5 familles de critères qui partagent leurs sources. Une recherche Tavily par famille (au lieu de 16), un seul appel Extract sur les URLs dédupliquées avec un budget réparti en round-robin, puis une extraction LLM par famille qui ne voit que ses pages et ne remplit que ses 2 à 4 champs — chacun avec sa valeur, son URL et sa citation. Toute erreur Tavily dégrade la famille concernée en `unknown` au lieu de remonter.

**Tech Stack :** Python 3.11, Pydantic v2 (`create_model` pour les schémas d'extraction par famille), `tavily-python`, pytest. Aucune nouvelle dépendance.

Spec : `docs/superpowers/specs/2026-07-14-tavily-fetcher-evidence-design.md`

## Global Constraints

- **Le LLM ne décide jamais d'un verdict.** Il extrait des faits sourcés ; la matrice et `grille.yaml` décident. Aucune tâche ne doit donner au LLM prise sur un verdict.
- **Les 16 champs scalaires de `ContractFacts` restent inchangés** (noms, `Literal`, défaut `"unknown"`). `build_arp`, `rules.py`, `grille.yaml` et leurs tests continuent de les lire tels quels.
- **Pas d'affirmation sans source :** un champ dont le LLM ne fournit pas de citation verbatim *et* d'URL retombe à `"unknown"`. Règle appliquée en Python, pas confiée au prompt.
- **Aucune exception Tavily ne remonte dans `Interview.assess`.**
- **Ne jamais journaliser de texte libre en clair** (contrainte `tracing.py`) : dans les traces, le contenu des pages passe par `mask_text()` ; seuls les noms de familles, les compteurs, les URLs et les types d'erreur sont écrits en clair.
- Répartition des familles (16 champs, chacun exactement une fois) :
  - `entrainement_reutilisation` : `trains_on_input`, `reentraining_opt_out`, `contract_prohibits_reuse`, `human_review`
  - `hebergement_retention` : `data_retention`, `data_residency`, `sub_processors`, `foreign_vendor_dependency`
  - `securite_technique` : `encryption_standard`, `authentication_support`, `audit_logging`, `incident_response`
  - `legal_pi` : `ip_ownership`, `applicable_law`
  - `termes_institutionnels` : `institutional_terms`, `quebec_higher_ed_license`
- Toute la suite tourne hors-ligne : `pytest -v` reste le seul gate.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `policybot/contract/families.py` *(créé)* | La table des 5 familles : nom, requête, champs (nom + valeurs permises + hint de normalisation), mots-clés de découpage. Donnée pure, zéro logique. |
| `policybot/contract/evidence.py` *(créé)* | `ContractEvidence` : l'évidence collectée, indexée par famille, plus la liste des familles en échec. Le seul type qui circule entre la collecte et l'extraction. |
| `policybot/models.py` *(modifié)* | `FactEvidence` (valeur + URL + citation + confiance + note) et le champ `ContractFacts.evidence`. |
| `policybot/contract/tavily.py` *(réécrit)* | Config YAML v2 par familles, collecte par famille, round-robin du budget d'extraction, dégradation par famille. |
| `policybot/contract/arp.py` *(modifié)* | Extraction LLM par famille avec citations, fusion en `ContractFacts`, découpage d'évidence piloté par les mots-clés de la famille, observations sourcées dans `build_arp`. |
| `policybot/interview/orchestrator.py` *(modifié)* | Câblage : le chemin Tavily et le chemin `fetch_terms` produisent tous deux un `ContractEvidence`. |
| `policybot/contract/tavily_probe.py` *(modifié)* | CLI adapté au `ContractEvidence`. |
| `tests/helpers/arp_fixtures.py` *(créé)* | `arp_extraction_responses(**valeurs)` : transforme un dict plat de faits en les 5 réponses par famille que le `FakeLLMProvider` doit servir. Évite de réécrire à la main les 8 fichiers de tests qui alimentent l'extraction ARP. |

---

### Task 1 : Familles de critères et modèle de preuve

**Files:**
- Create: `policybot/contract/families.py`
- Create: `policybot/contract/evidence.py`
- Modify: `policybot/models.py` (après `ContractFacts`, ligne 54)
- Test: `tests/contract/test_families.py`

**Interfaces:**
- Consumes: `policybot.contract.fetcher.FetchedTerms` (Pydantic : `text: str`, `source_url: str`, `fetched_at: date`).
- Produces:
  - `FactField(name: str, allowed_values: tuple[str, ...], hint: str)` — dataclass frozen.
  - `FactFamily(name: str, query: str, fields: tuple[FactField, ...], keywords: tuple[str, ...])` — dataclass frozen ; `query` est un gabarit contenant `{tool}` et `{vendor}`.
  - `FACT_FAMILIES: tuple[FactFamily, ...]` (5 entrées), `ALL_FACT_FIELDS: tuple[FactField, ...]` (16 entrées), `family_by_name(name: str) -> FactFamily | None`.
  - `ContractEvidence(by_family: dict[str, FetchedTerms], failed_families: tuple[str, ...])` avec `from_single(terms: FetchedTerms) -> ContractEvidence`, `primary_source_url() -> str | None`, `is_empty() -> bool`.
  - `FactEvidence` (Pydantic) et `ContractFacts.evidence: dict[str, FactEvidence]`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/contract/test_families.py` :

```python
from datetime import date

from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import (
    ALL_FACT_FIELDS,
    FACT_FAMILIES,
    family_by_name,
)
from policybot.contract.fetcher import FetchedTerms
from policybot.models import ContractFacts, FactEvidence

CONTRACT_FACT_FIELDS = {
    "trains_on_input", "data_retention", "data_residency", "sub_processors",
    "human_review", "encryption_standard", "ip_ownership", "applicable_law",
    "foreign_vendor_dependency", "contract_prohibits_reuse", "reentraining_opt_out",
    "authentication_support", "audit_logging", "institutional_terms",
    "quebec_higher_ed_license", "incident_response",
}


def test_families_cover_every_contract_fact_field_exactly_once():
    names = [field.name for family in FACT_FAMILIES for field in family.fields]

    assert len(FACT_FAMILIES) == 5
    assert len(names) == len(set(names)) == 16
    assert set(names) == CONTRACT_FACT_FIELDS
    assert {field.name for field in ALL_FACT_FIELDS} == CONTRACT_FACT_FIELDS


def test_family_allowed_values_match_contract_facts_literals():
    literals = {
        name: set(info.annotation.__args__)
        for name, info in ContractFacts.model_fields.items()
        if name in CONTRACT_FACT_FIELDS
    }

    for field in ALL_FACT_FIELDS:
        assert set(field.allowed_values) == literals[field.name], field.name
        assert "unknown" in field.allowed_values


def test_every_family_has_a_query_template_and_keywords():
    for family in FACT_FAMILIES:
        assert "{tool}" in family.query and "{vendor}" in family.query
        assert family.keywords


def test_family_by_name_returns_none_for_unknown_family():
    assert family_by_name("entrainement_reutilisation") is FACT_FAMILIES[0]
    assert family_by_name("famille_inexistante") is None


def test_contract_evidence_from_single_feeds_every_family():
    terms = FetchedTerms(
        text="CGU complètes", source_url="https://example.test/cgu", fetched_at=date.today(),
    )

    evidence = ContractEvidence.from_single(terms)

    assert set(evidence.by_family) == {family.name for family in FACT_FAMILIES}
    assert evidence.primary_source_url() == "https://example.test/cgu"
    assert evidence.failed_families == ()
    assert not evidence.is_empty()


def test_empty_contract_evidence_is_empty():
    assert ContractEvidence(by_family={}).is_empty()
    assert ContractEvidence(by_family={}).primary_source_url() is None


def test_contract_facts_carries_per_field_evidence():
    facts = ContractFacts(
        trains_on_input="no",
        evidence={"trains_on_input": FactEvidence(
            value="no",
            source_url="https://example.test/cgu",
            quote="We do not train our models on your business data.",
            confidence=0.9,
        )},
    )

    assert facts.evidence["trains_on_input"].quote.startswith("We do not train")
    assert ContractFacts().evidence == {}
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_families.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policybot.contract.families'`

- [ ] **Step 3 : Écrire `policybot/contract/families.py`**

```python
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
```

- [ ] **Step 4 : Écrire `policybot/contract/evidence.py`**

```python
"""L'évidence contractuelle collectée, indexée par famille de critères."""
from __future__ import annotations

from dataclasses import dataclass, field

from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms


@dataclass
class ContractEvidence:
    by_family: dict[str, FetchedTerms]
    failed_families: tuple[str, ...] = field(default=())

    @classmethod
    def from_single(cls, terms: FetchedTerms) -> "ContractEvidence":
        """Chemin de repli `fetch_terms` : une seule page nourrit toutes les familles."""
        return cls(by_family={family.name: terms for family in FACT_FAMILIES})

    def primary_source_url(self) -> str | None:
        for family in FACT_FAMILIES:
            terms = self.by_family.get(family.name)
            if terms is not None:
                return terms.source_url
        return None

    def is_empty(self) -> bool:
        return not self.by_family
```

- [ ] **Step 5 : Ajouter `FactEvidence` et `ContractFacts.evidence` dans `policybot/models.py`**

Insérer `FactEvidence` juste avant `class ContractFacts` (ligne 30) :

```python
class FactEvidence(BaseModel):
    """La preuve d'un fait contractuel : sa valeur, sa source, sa citation.

    `note` explique une valeur `unknown` non concluante (collecte échouée,
    citation manquante) — c'est ce que l'officier lit dans le rapport.
    """
    value: str = "unknown"
    source_url: Optional[str] = None
    quote: Optional[str] = None
    confidence: float = 0.0
    note: Optional[str] = None
```

Puis, dans `ContractFacts`, ajouter après `extraction_confidence: float = 0.0` (ligne 54) :

```python
    evidence: dict[str, FactEvidence] = Field(default_factory=dict)
```

Vérifier que `Field` est importé depuis `pydantic` en tête de `models.py` ; l'ajouter à l'import existant si absent.

- [ ] **Step 6 : Lancer les tests pour vérifier qu'ils passent**

Run: `pytest tests/contract/test_families.py -v`
Expected: PASS (7 tests)

Run: `pytest -q`
Expected: PASS — aucune régression (les 16 champs scalaires sont intacts, `evidence` a un défaut vide).

- [ ] **Step 7 : Commit**

```bash
git add policybot/contract/families.py policybot/contract/evidence.py policybot/models.py tests/contract/test_families.py
git commit -m "feat(contract): familles de critères et modèle de preuve par champ"
```

---

### Task 2 : Config YAML v2 par familles

**Files:**
- Modify: `policybot/contract/tavily.py:17-97` (remplacer `FACT_FIELDS`), `:144-212` (build/ensure/load)
- Test: `tests/contract/test_tavily_config.py` *(créé)*

**Interfaces:**
- Consumes: `FACT_FAMILIES`, `FactFamily` (Task 1) ; `lookup_tool` (`policybot/classify/tool_registry.py`).
- Produces:
  - `CONFIG_SCHEMA_VERSION: int = 2`
  - `build_contract_search_config(tool_name: str) -> dict` — clés : `schema_version`, `tool`, `search_defaults`, `extract_defaults`, `families`. Chaque entrée de `families` : `{name, query, fields: [{name, allowed_values}]}`.
  - `ensure_contract_search_config(tool_name: str, config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Path` — régénère le fichier si `schema_version` est absent ou < `CONFIG_SCHEMA_VERSION`.
  - `load_contract_search_config(path: Path | str) -> dict` — exige une liste `families`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/contract/test_tavily_config.py` :

```python
import yaml

from policybot.contract.families import FACT_FAMILIES
from policybot.contract.tavily import (
    CONFIG_SCHEMA_VERSION,
    build_contract_search_config,
    ensure_contract_search_config,
    load_contract_search_config,
)


def test_config_declares_one_entry_per_family():
    config = build_contract_search_config("ChatGPT")

    assert config["schema_version"] == CONFIG_SCHEMA_VERSION
    assert config["tool"]["vendor"] == "OpenAI"
    assert config["search_defaults"]["include_domains"] == ["openai.com"]
    assert [family["name"] for family in config["families"]] == [
        family.name for family in FACT_FAMILIES
    ]
    assert all("ChatGPT" in family["query"] for family in config["families"])
    assert all("OpenAI" in family["query"] for family in config["families"])

    fields = [f for family in config["families"] for f in family["fields"]]
    assert len(fields) == 16
    trains = next(f for f in fields if f["name"] == "trains_on_input")
    assert trains["allowed_values"] == ["yes", "no", "opt_out_available", "unknown"]


def test_unknown_tool_falls_back_to_its_own_name_as_vendor():
    config = build_contract_search_config("OutilInconnu")

    assert config["tool"]["vendor"] == ""
    assert config["search_defaults"]["include_domains"] == []
    assert all("OutilInconnu" in family["query"] for family in config["families"])


def test_ensure_config_writes_once_then_reuses(tmp_path):
    path = ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path)

    assert path.name == "chatgpt-pro.yaml"
    loaded = load_contract_search_config(path)
    assert len(loaded["families"]) == len(FACT_FAMILIES)

    path.write_text(
        yaml.safe_dump({"schema_version": CONFIG_SCHEMA_VERSION, "families": []}),
        encoding="utf-8",
    )
    assert ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path) == path
    assert load_contract_search_config(path)["families"] == []


def test_ensure_config_regenerates_a_stale_schema(tmp_path):
    path = tmp_path / "chatgpt.yaml"
    path.write_text(
        yaml.safe_dump({"tool": {"name": "ChatGPT"}, "fields": [{"name": "trains_on_input"}]}),
        encoding="utf-8",
    )

    ensure_contract_search_config("ChatGPT", config_dir=tmp_path)
    regenerated = load_contract_search_config(path)

    assert regenerated["schema_version"] == CONFIG_SCHEMA_VERSION
    assert len(regenerated["families"]) == len(FACT_FAMILIES)
    assert "fields" not in regenerated


def test_load_config_rejects_a_config_without_families(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("tool:\n  name: X\n", encoding="utf-8")

    try:
        load_contract_search_config(path)
    except ValueError as exc:
        assert "families" in str(exc)
    else:
        raise AssertionError("load_contract_search_config should reject a config without families")
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_tavily_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'CONFIG_SCHEMA_VERSION'`

- [ ] **Step 3 : Remplacer `FACT_FIELDS` et les fonctions de config dans `policybot/contract/tavily.py`**

Supprimer la constante `FACT_FIELDS` (lignes 17-97) et remplacer les fonctions `build_contract_search_config` / `ensure_contract_search_config` / `load_contract_search_config` (lignes 144-212) par :

```python
from policybot.contract.families import FACT_FAMILIES

CONFIG_SCHEMA_VERSION = 2


def build_contract_search_config(tool_name: str) -> dict:
    entry = lookup_tool(tool_name) or {}
    vendor = entry.get("vendor") or ""
    terms_url = entry.get("terms_url") or ""
    domain = _domain_from_url(terms_url)
    context = {"tool": tool_name, "vendor": vendor or tool_name}

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "tool": {"name": tool_name, "vendor": vendor, "terms_url": terms_url},
        "search_defaults": {
            "search_depth": "advanced",
            "max_results": 5,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": True,
            "include_images": False,
            "include_favicon": False,
            "country": "canada",
            "safe_search": False,
            "include_domains": [domain] if domain else [],
        },
        "extract_defaults": {
            "extract_depth": "advanced",
            "format": "markdown",
            "include_images": False,
            "include_favicon": False,
            "timeout": 30,
            "max_urls": 20,
        },
        "families": [
            {
                "name": family.name,
                "query": family.query.format(**context),
                "fields": [
                    {"name": field.name, "allowed_values": list(field.allowed_values)}
                    for field in family.fields
                ],
            }
            for family in FACT_FAMILIES
        ],
    }


def _is_stale(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return True
    if not isinstance(existing, dict):
        return True
    return int(existing.get("schema_version", 0)) < CONFIG_SCHEMA_VERSION


def ensure_contract_search_config(
    tool_name: str,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> Path:
    directory = Path(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slugify(tool_name)}.yaml"
    if not path.exists() or _is_stale(path):
        path.write_text(
            yaml.safe_dump(
                build_contract_search_config(tool_name),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return path


def load_contract_search_config(path: Path | str) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if not isinstance(config, dict):
        raise ValueError("Tavily contract config must be a YAML object.")
    if not isinstance(config.get("families"), list):
        raise ValueError("Tavily contract config must define a families list.")
    return config
```

Note : `tavily.py` ne compile pas encore — `collect_terms_from_tavily` (ligne 288) référence toujours `config["fields"]`. C'est la Task 3. Pour garder l'arbre vert entre les deux commits, remplacer temporairement le corps de `collect_terms_from_tavily` et `search_contract_terms_with_tavily` par `raise NotImplementedError("remplacé en Task 3")` **et** marquer les tests correspondants de `tests/contract/test_tavily.py` avec `@pytest.mark.skip(reason="réécrit en Task 3")`.

- [ ] **Step 4 : Lancer les tests**

Run: `pytest tests/contract/test_tavily_config.py -v`
Expected: PASS (5 tests)

Run: `pytest -q`
Expected: PASS, avec les tests de collecte Tavily marqués `skipped`.

- [ ] **Step 5 : Supprimer les configs YAML v1 déjà générées**

```bash
git rm -r --ignore-unmatch configs/tavily_contracts
```

Elles se régénèrent automatiquement au schéma v2 au premier appel — les garder ne ferait que déclencher la régénération, autant ne pas versionner du contenu périmé.

- [ ] **Step 6 : Commit**

```bash
git add policybot/contract/tavily.py tests/contract/test_tavily_config.py
git commit -m "feat(tavily): config YAML v2 par familles, régénération du schéma périmé"
```

---

### Task 3 : Collecte par familles, budget en round-robin

**Files:**
- Modify: `policybot/contract/tavily.py` (remplacer `collect_terms_from_tavily`, lignes 288-328)
- Test: `tests/contract/test_tavily_collect.py` *(créé)*

**Interfaces:**
- Consumes: `ContractEvidence` (Task 1), config v2 (Task 2).
- Produces: `collect_evidence_from_tavily(config: dict, search_func, extract_func=None) -> ContractEvidence`.
  - `search_func(query=..., **search_kwargs) -> dict` (contrat de `TavilyClient.search`).
  - `extract_func(urls: list[str], **extract_kwargs) -> dict` (contrat de `TavilyClient.extract`).
  - Le budget d'extraction est `max_urls // nb_familles` URLs par famille (4 pour 5 familles), pris dans l'ordre de rang Tavily, en round-robin sur les familles ; le total est plafonné à 20 (limite Tavily).
  - Une URL trouvée par deux familles n'est extraite qu'une fois et nourrit les deux.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/contract/test_tavily_collect.py` :

```python
import pytest

from policybot.contract.tavily import collect_evidence_from_tavily

CONFIG = {
    "tool": {"name": "ToolX"},
    "search_defaults": {"max_results": 5, "include_raw_content": True},
    "extract_defaults": {"extract_depth": "advanced", "format": "markdown", "max_urls": 20},
    "families": [
        {"name": "entrainement_reutilisation", "query": "ToolX training", "fields": []},
        {"name": "securite_technique", "query": "ToolX security", "fields": []},
    ],
}


def test_one_search_per_family_and_evidence_indexed_by_family():
    queries = []

    def search(**kwargs):
        queries.append(kwargs["query"])
        slug = "training" if "training" in kwargs["query"] else "security"
        return {"results": [{"url": f"https://example.test/{slug}", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [
            {"url": url, "raw_content": f"Contenu complet de {url}"} for url in urls
        ]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert queries == ["ToolX training", "ToolX security"]
    assert set(evidence.by_family) == {"entrainement_reutilisation", "securite_technique"}
    assert "Contenu complet de https://example.test/training" in (
        evidence.by_family["entrainement_reutilisation"].text
    )
    assert "security" not in evidence.by_family["entrainement_reutilisation"].text
    assert evidence.failed_families == ()


def test_a_url_found_by_two_families_is_extracted_once_and_feeds_both():
    extract_calls = []

    def search(**kwargs):
        return {"results": [{"url": "https://example.test/cgu", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        extract_calls.append(list(urls))
        return {"results": [{"url": "https://example.test/cgu", "raw_content": "CGU partagées"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert extract_calls == [["https://example.test/cgu"]]
    assert "CGU partagées" in evidence.by_family["entrainement_reutilisation"].text
    assert "CGU partagées" in evidence.by_family["securite_technique"].text


def test_extraction_budget_is_shared_round_robin_between_families():
    def search(**kwargs):
        slug = "t" if "training" in kwargs["query"] else "s"
        return {"results": [
            {"url": f"https://example.test/{slug}{index}", "content": "Snippet"}
            for index in range(10)
        ]}

    captured = {}

    def extract(urls, **kwargs):
        captured["urls"] = list(urls)
        return {"results": [{"url": url, "raw_content": f"Contenu {url}"} for url in urls]}

    collect_evidence_from_tavily(CONFIG, search, extract)

    urls = captured["urls"]
    assert len(urls) == 20
    assert sum(1 for url in urls if "/t" in url) == 10
    assert sum(1 for url in urls if "/s" in url) == 10
    assert urls[0].endswith("/t0") and urls[1].endswith("/s0")


def test_falls_back_to_search_content_when_extract_is_unavailable():
    def search(**kwargs):
        return {"results": [{
            "url": "https://example.test/terms",
            "title": "Terms",
            "content": "Évidence issue de la recherche, sans Extract.",
        }]}

    evidence = collect_evidence_from_tavily(CONFIG, search)

    terms = evidence.by_family["entrainement_reutilisation"]
    assert "Source recherche Tavily" in terms.text
    assert "Évidence issue de la recherche" in terms.text
    assert terms.source_url == "https://example.test/terms"


def test_a_family_without_results_is_absent_from_the_evidence():
    def search(**kwargs):
        if "training" in kwargs["query"]:
            return {"results": []}
        return {"results": [{"url": "https://example.test/security", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [{"url": urls[0], "raw_content": "Contenu sécurité"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert "entrainement_reutilisation" not in evidence.by_family
    assert "securite_technique" in evidence.by_family
    assert not evidence.is_empty()
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_tavily_collect.py -v`
Expected: FAIL — `ImportError: cannot import name 'collect_evidence_from_tavily'`

- [ ] **Step 3 : Écrire la collecte dans `policybot/contract/tavily.py`**

Remplacer `collect_terms_from_tavily` et ses helpers devenus morts (`_unique_urls`, `_fallback_search_chunks`, `_search_kwargs`, `_extract_max_urls`) par le code ci-dessous. Conserver `_response_results`, `_extract_result_content`, `_extract_kwargs`, `SEARCH_KEYS`, `EXTRACT_KEYS`, `_slugify` et `_domain_from_url`, qui restent utilisés.

```python
TAVILY_EXTRACT_HARD_LIMIT = 20


def _family_search_kwargs(config: dict, family: dict) -> dict:
    merged = dict(config.get("search_defaults") or {})
    merged.update(family.get("search") or {})
    return {
        key: value
        for key, value in merged.items()
        if key in SEARCH_KEYS and value not in (None, "")
    }


def _round_robin_urls(urls_by_family: dict[str, list[str]], budget: int) -> list[str]:
    """Un quota égal par famille, servi en alternance, plafonné à la limite Tavily.

    Sert la première URL de chaque famille, puis la deuxième, etc. — sans quoi
    les familles interrogées en premier mangeraient tout le budget.
    """
    per_family = max(1, budget // max(1, len(urls_by_family)))
    ordered: list[str] = []
    seen: set[str] = set()
    for rank in range(per_family):
        for urls in urls_by_family.values():
            if rank >= len(urls):
                continue
            url = urls[rank]
            if url in seen:
                continue
            seen.add(url)
            ordered.append(url)
            if len(ordered) >= budget:
                return ordered
    return ordered


def _extract_budget(config: dict) -> int:
    defaults = dict(config.get("extract_defaults") or {})
    try:
        configured = int(defaults.get("max_urls", TAVILY_EXTRACT_HARD_LIMIT))
    except (TypeError, ValueError):
        configured = TAVILY_EXTRACT_HARD_LIMIT
    return max(1, min(configured, TAVILY_EXTRACT_HARD_LIMIT))


def _family_chunk(url: str, content: str, extracted: bool) -> str:
    origin = "Source extraite Tavily" if extracted else "Source recherche Tavily"
    return f"{origin}\nURL: {url}\n{content}"


def collect_evidence_from_tavily(
    config: dict, search_func, extract_func=None,
) -> ContractEvidence:
    families = config["families"]
    urls_by_family: dict[str, list[str]] = {}
    search_hits: dict[str, dict[str, dict]] = {}  # famille → url → résultat de recherche

    for family in families:
        query = family.get("query")
        if not query:
            continue
        response = search_func(query=query, **_family_search_kwargs(config, family))
        hits: dict[str, dict] = {}
        for result in _response_results(response):
            url = result.get("url") or ""
            if url and url not in hits:
                hits[url] = result
        if hits:
            urls_by_family[family["name"]] = list(hits)
            search_hits[family["name"]] = hits

    selected = _round_robin_urls(urls_by_family, _extract_budget(config))
    extracted_by_url: dict[str, str] = {}
    if selected and extract_func is not None:
        response = extract_func(selected, **_extract_kwargs(config))
        for result in _response_results(response):
            url = result.get("url") or ""
            content = _extract_result_content(result)
            if url and content:
                extracted_by_url[url] = content

    by_family: dict[str, FetchedTerms] = {}
    for name, hits in search_hits.items():
        chunks: list[str] = []
        for url, result in hits.items():
            if url in extracted_by_url:
                chunks.append(_family_chunk(url, extracted_by_url[url], extracted=True))
                continue
            content = result.get("raw_content") or result.get("content") or ""
            if content:
                chunks.append(_family_chunk(url, content, extracted=False))
        if chunks:
            by_family[name] = FetchedTerms(
                text="\n\n---\n\n".join(chunks),
                source_url=next(iter(hits)),
                fetched_at=date.today(),
            )

    return ContractEvidence(by_family=by_family)
```

Ajouter l'import `from policybot.contract.evidence import ContractEvidence` en tête de fichier.

- [ ] **Step 4 : Lancer les tests**

Run: `pytest tests/contract/test_tavily_collect.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5 : Commit**

```bash
git add policybot/contract/tavily.py tests/contract/test_tavily_collect.py
git commit -m "feat(tavily): collecte par famille, budget d'extraction en round-robin"
```

---

### Task 4 : Dégradation par famille au lieu du crash

**Files:**
- Modify: `policybot/contract/tavily.py` (`collect_evidence_from_tavily`, `search_contract_terms_with_tavily`)
- Test: `tests/contract/test_tavily_errors.py` *(créé)*

**Interfaces:**
- Consumes: `collect_evidence_from_tavily` (Task 3), `trace_step` (`policybot/tracing.py`).
- Produces:
  - `_error_kind(exc: Exception) -> str` → `"auth"` | `"quota"` | `"network"`.
  - `collect_evidence_from_tavily` n'émet plus aucune exception : une recherche en échec ajoute la famille à `ContractEvidence.failed_families` ; un Extract en échec fait basculer toutes les familles sur le `content` de recherche.
  - `search_contract_terms_with_tavily(tool_name, *, api_key=None, config_dir=DEFAULT_CONFIG_DIR, client=None) -> ContractEvidence | None` — `None` si pas de clé API, si le client ne peut pas être construit, ou si l'évidence est vide.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/contract/test_tavily_errors.py` :

```python
import httpx

from policybot.contract.tavily import (
    _error_kind,
    collect_evidence_from_tavily,
    search_contract_terms_with_tavily,
)

CONFIG = {
    "tool": {"name": "ToolX"},
    "search_defaults": {"max_results": 5},
    "extract_defaults": {"max_urls": 20},
    "families": [
        {"name": "entrainement_reutilisation", "query": "ToolX training", "fields": []},
        {"name": "securite_technique", "query": "ToolX security", "fields": []},
    ],
}


def test_a_failed_family_search_degrades_only_that_family():
    def search(**kwargs):
        if "training" in kwargs["query"]:
            raise httpx.ConnectError("tavily unreachable")
        return {"results": [{"url": "https://example.test/security", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [{"url": urls[0], "raw_content": "Contenu sécurité"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert evidence.failed_families == ("entrainement_reutilisation",)
    assert "entrainement_reutilisation" not in evidence.by_family
    assert "Contenu sécurité" in evidence.by_family["securite_technique"].text


def test_a_failed_extract_falls_back_to_search_content():
    def search(**kwargs):
        return {"results": [{
            "url": "https://example.test/terms",
            "content": "Évidence de recherche conservée malgré l'échec d'Extract.",
        }]}

    def extract(urls, **kwargs):
        raise httpx.ReadTimeout("extract timed out")

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert evidence.failed_families == ()
    assert "Évidence de recherche conservée" in (
        evidence.by_family["entrainement_reutilisation"].text
    )


def test_every_family_failing_yields_empty_evidence():
    def search(**kwargs):
        raise httpx.ConnectError("tavily unreachable")

    evidence = collect_evidence_from_tavily(CONFIG, search)

    assert evidence.is_empty()
    assert set(evidence.failed_families) == {"entrainement_reutilisation", "securite_technique"}


def test_error_kind_distinguishes_auth_quota_and_network():
    class InvalidAPIKeyError(Exception):
        pass

    class UsageLimitExceededError(Exception):
        pass

    assert _error_kind(InvalidAPIKeyError("bad key")) == "auth"
    assert _error_kind(UsageLimitExceededError("plan limit")) == "quota"
    assert _error_kind(httpx.ConnectError("boom")) == "network"


def test_search_returns_none_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert search_contract_terms_with_tavily("ChatGPT", config_dir=tmp_path) is None


def test_search_returns_none_when_all_families_fail(tmp_path):
    class BrokenClient:
        def search(self, **kwargs):
            raise httpx.ConnectError("tavily unreachable")

        def extract(self, urls, **kwargs):
            raise AssertionError("extract should not run when every search failed")

    assert search_contract_terms_with_tavily(
        "ChatGPT", api_key="unused", config_dir=tmp_path, client=BrokenClient(),
    ) is None
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_tavily_errors.py -v`
Expected: FAIL — `ImportError: cannot import name '_error_kind'`

- [ ] **Step 3 : Ajouter la robustesse dans `policybot/contract/tavily.py`**

```python
from policybot.tracing import trace_step


def _error_kind(exc: Exception) -> str:
    """« Ta clé est épuisée » et « la page ne répond pas » n'appellent pas la même réaction."""
    name = type(exc).__name__
    message = str(exc)
    if "APIKey" in name or "401" in message or "403" in message:
        return "auth"
    if "UsageLimit" in name or "429" in message or "quota" in message.lower():
        return "quota"
    return "network"
```

Dans `collect_evidence_from_tavily`, envelopper la recherche par famille :

```python
    for family in families:
        query = family.get("query")
        if not query:
            continue
        name = family["name"]
        with trace_step(None, "tavily_family_search", family=name) as extra:
            try:
                response = search_func(query=query, **_family_search_kwargs(config, family))
            except Exception as exc:  # noqa: BLE001 — une famille perdue ne doit pas tuer l'entrevue
                failed.append(name)
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
                continue
            hits: dict[str, dict] = {}
            for result in _response_results(response):
                url = result.get("url") or ""
                if url and url not in hits:
                    hits[url] = result
            extra["outcome"] = "ok"
            extra["hits"] = len(hits)
        if hits:
            urls_by_family[name] = list(hits)
            search_hits[name] = hits
```

Déclarer `failed: list[str] = []` au début de la fonction et retourner `ContractEvidence(by_family=by_family, failed_families=tuple(failed))`.

Envelopper de même l'appel Extract :

```python
    if selected and extract_func is not None:
        with trace_step(None, "tavily_extract", urls=len(selected)) as extra:
            try:
                response = extract_func(selected, **_extract_kwargs(config))
            except Exception as exc:  # noqa: BLE001 — repli sur le contenu de recherche
                response = {}
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
            else:
                extra["outcome"] = "ok"
            for result in _response_results(response):
                url = result.get("url") or ""
                content = _extract_result_content(result)
                if url and content:
                    extracted_by_url[url] = content
            extra["extracted"] = len(extracted_by_url)
```

Ne rien journaliser du contenu des pages : seuls des compteurs, des noms de familles et des types d'erreur passent dans `trace_step` (contrainte `tracing.py`).

Enfin, réécrire `search_contract_terms_with_tavily` :

```python
def search_contract_terms_with_tavily(
    tool_name: str,
    *,
    api_key: str | None = None,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    client=None,
) -> ContractEvidence | None:
    path = ensure_contract_search_config(tool_name, config_dir=config_dir)
    config = load_contract_search_config(path)

    tavily_client = client
    should_close = False
    if tavily_client is None:
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            return None
        try:
            from tavily import TavilyClient

            tavily_client = TavilyClient(api_key=key)
        except Exception as exc:  # noqa: BLE001 — clé invalide ou paquet absent
            with trace_step(None, "tavily_client_init") as extra:
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
            return None
        should_close = True

    try:
        evidence = collect_evidence_from_tavily(
            config, tavily_client.search, tavily_client.extract,
        )
    finally:
        if should_close and hasattr(tavily_client, "close"):
            tavily_client.close()

    return None if evidence.is_empty() else evidence
```

Supprimer la fonction `collect_terms_from_tavily` et les tests qui la ciblaient dans `tests/contract/test_tavily.py` (fichier remplacé par `test_tavily_config.py`, `test_tavily_collect.py` et `test_tavily_errors.py`) — sauf `test_interview_uses_injected_tavily_terms_before_direct_fetch`, à déplacer tel quel dans `tests/contract/test_tavily_errors.py` puis à adapter en Task 6.

- [ ] **Step 4 : Lancer les tests**

Run: `pytest tests/contract/test_tavily_errors.py tests/contract/test_tavily_collect.py tests/contract/test_tavily_config.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add policybot/contract/tavily.py tests/contract/
git commit -m "feat(tavily): dégradation par famille, aucune exception ne remonte"
```

---

### Task 5 : Extraction LLM par famille, avec citations

**Files:**
- Modify: `policybot/contract/arp.py:16-246` (remplacer `ContractFactsExtraction`, `_FIELD_INSTRUCTIONS`, `_KEYWORD_PATTERNS`, `_select_evidence_text`, `_build_extraction_prompt`, `extract_contract_facts`)
- Create: `tests/helpers/__init__.py`, `tests/helpers/arp_fixtures.py`
- Test: `tests/contract/test_arp_extraction.py` *(créé)*

**Interfaces:**
- Consumes: `FACT_FAMILIES`, `FactFamily`, `FactField` (Task 1) ; `ContractEvidence` (Task 1) ; `LLMProvider.complete_structured(system, user, schema, *, run_name, tags)`.
- Produces:
  - `FieldExtraction` (Pydantic) : `value: str = "unknown"`, `source_url: str | None`, `quote: str | None`, `confidence: float`.
  - `family_extraction_model(family: FactFamily) -> type[BaseModel]` — un modèle Pydantic dont chaque attribut est le nom d'un champ de la famille, typé `FieldExtraction`.
  - `extract_contract_facts(evidence: ContractEvidence, llm: LLMProvider) -> ContractFacts` — **la signature change** : elle prend un `ContractEvidence`, plus un `FetchedTerms`.
  - `arp_extraction_responses(**values) -> list[dict]` (helper de test) : à partir d'un dict plat `trains_on_input="no", ...`, produit les 5 payloads que `FakeLLMProvider` doit servir, dans l'ordre de `FACT_FAMILIES`.

- [ ] **Step 1 : Écrire le helper de fixtures**

Créer `tests/helpers/__init__.py` (vide) et `tests/helpers/arp_fixtures.py` :

```python
"""Traduit un dict plat de faits contractuels en réponses LLM par famille.

L'extraction ARP fait désormais un appel LLM par famille (5), chacun rendant
{value, source_url, quote, confidence} par champ. Les tests continuent d'écrire
`trains_on_input="no"` et ce helper fabrique les 5 payloads correspondants.
"""
from policybot.contract.families import FACT_FAMILIES

DEFAULT_URL = "https://example.test/evidence"


def arp_extraction_responses(_url: str = DEFAULT_URL, **values) -> list[dict]:
    unknown_fields = set(values) - {
        field.name for family in FACT_FAMILIES for field in family.fields
    }
    if unknown_fields:
        raise AssertionError(f"champs inconnus dans la fixture ARP: {sorted(unknown_fields)}")

    responses = []
    for family in FACT_FAMILIES:
        payload = {}
        for field in family.fields:
            value = values.get(field.name, "unknown")
            payload[field.name] = {
                "value": value,
                "source_url": _url,
                "quote": f"Extrait de preuve pour {field.name}.",
                "confidence": 0.9,
            }
        responses.append(payload)
    return responses
```

- [ ] **Step 2 : Écrire le test qui échoue**

Créer `tests/contract/test_arp_extraction.py` :

```python
from datetime import date

import pytest

from policybot.contract.arp import extract_contract_facts, family_extraction_model
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.fake import FakeLLMProvider

from tests.helpers.arp_fixtures import arp_extraction_responses


def _evidence(text: str = "Preuve contractuelle.") -> ContractEvidence:
    return ContractEvidence.from_single(FetchedTerms(
        text=text, source_url="https://example.test/cgu", fetched_at=date(2026, 7, 14),
    ))


def test_family_extraction_model_declares_only_its_own_fields():
    model = family_extraction_model(FACT_FAMILIES[0])

    assert set(model.model_fields) == {
        field.name for field in FACT_FAMILIES[0].fields
    }


def test_one_llm_call_per_family_each_prompt_scoped_to_its_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        trains_on_input="no", data_residency="canada", encryption_standard="strong",
    ))

    facts = extract_contract_facts(_evidence(), llm)

    assert len(llm.calls) == len(FACT_FAMILIES)
    assert facts.trains_on_input == "no"
    assert facts.data_residency == "canada"
    assert facts.encryption_standard == "strong"

    training_prompt = llm.calls[0][1]
    assert "trains_on_input" in training_prompt
    assert "encryption_standard" not in training_prompt


def test_each_fact_carries_its_url_and_verbatim_quote():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(trains_on_input="yes"))

    facts = extract_contract_facts(_evidence(), llm)

    proof = facts.evidence["trains_on_input"]
    assert proof.value == "yes"
    assert proof.source_url == "https://example.test/evidence"
    assert proof.quote == "Extrait de preuve pour trains_on_input."
    assert proof.confidence == 0.9


def test_a_value_without_a_quote_is_demoted_to_unknown():
    responses = arp_extraction_responses(trains_on_input="no")
    responses[0]["trains_on_input"]["quote"] = ""

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.trains_on_input == "unknown"
    assert facts.evidence["trains_on_input"].note == "valeur écartée: aucune citation vérifiable"


def test_a_value_outside_the_allowed_set_is_demoted_to_unknown():
    responses = arp_extraction_responses(trains_on_input="no")
    responses[0]["trains_on_input"]["value"] = "peut-être"

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.trains_on_input == "unknown"


def test_a_failed_family_leaves_its_fields_unknown_and_annotated():
    evidence = _evidence()
    del evidence.by_family["entrainement_reutilisation"]
    evidence.failed_families = ("entrainement_reutilisation",)
    responses = arp_extraction_responses(data_residency="canada")[1:]

    facts = extract_contract_facts(evidence, FakeLLMProvider(json_responses=responses))

    assert facts.trains_on_input == "unknown"
    assert facts.evidence["trains_on_input"].note == "collecte Tavily échouée"
    assert facts.data_residency == "canada"


def test_a_family_llm_failure_degrades_only_that_family():
    class HalfBrokenLLM(FakeLLMProvider):
        def complete_structured(self, system, user, schema, **kwargs):
            if "trains_on_input" in user:
                raise RuntimeError("le modèle a renvoyé du JSON invalide")
            return super().complete_structured(system, user, schema, **kwargs)

    llm = HalfBrokenLLM(json_responses=arp_extraction_responses(data_residency="canada")[1:])

    facts = extract_contract_facts(_evidence(), llm)

    assert facts.trains_on_input == "unknown"
    assert facts.evidence["trains_on_input"].note == "extraction LLM échouée"
    assert facts.data_residency == "canada"


def test_oversized_family_evidence_is_trimmed_with_that_family_s_keywords():
    filler = "Texte non pertinent. " * 3000
    text = (
        filler
        + " We do not use your business data to train our models. "
        + filler
        + " Data is encrypted at rest and in transit. "
        + filler
    )
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(trains_on_input="no"))

    extract_contract_facts(_evidence(text), llm)

    training_prompt = llm.calls[0][1]
    assert "train our models" in training_prompt
    assert "encrypted at rest" not in training_prompt
    assert len(training_prompt) < len(text)


def test_source_url_and_fetched_at_come_from_the_evidence():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses())

    facts = extract_contract_facts(_evidence(), llm)

    assert facts.source_url == "https://example.test/cgu"
    assert facts.fetched_at == date(2026, 7, 14)


def test_empty_evidence_yields_all_unknown_without_calling_the_llm():
    llm = FakeLLMProvider(json_responses=[])

    facts = extract_contract_facts(ContractEvidence(by_family={}), llm)

    assert llm.calls == []
    assert facts.trains_on_input == "unknown"
    assert facts.extraction_confidence == 0.0
```

- [ ] **Step 3 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_arp_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'family_extraction_model'`

- [ ] **Step 4 : Réécrire l'extraction dans `policybot/contract/arp.py`**

Remplacer tout le bloc allant de `class ContractFactsExtraction` (ligne 16) à la fin de `extract_contract_facts` (ligne 246) par :

```python
from statistics import mean

from pydantic import BaseModel, Field, create_model

from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import FACT_FAMILIES, FactFamily, FactField
from policybot.models import FactEvidence
from policybot.tracing import trace_step

CURRENT_ARP_SCHEMA_VERSION = 2

_MAX_FAMILY_EVIDENCE_CHARS = 8000
_SOURCE_SEPARATOR = "\n\n---\n\n"
_MAX_QUOTE_CHARS = 300

_SYSTEM = (
    "You extract normalized contract facts for an AI tool. Return only one JSON "
    "object. Use only the allowed values listed in the prompt. Answer unknown "
    "when the evidence does not allow a conclusion. Do not infer guarantees "
    "that are not written in the evidence. For every field, quote verbatim the "
    "sentence from the evidence that supports the value, and give the URL of the "
    "source it came from. If you cannot quote the evidence, answer unknown."
)


class FieldExtraction(BaseModel):
    value: str = "unknown"
    source_url: Optional[str] = None
    quote: Optional[str] = Field(
        None, description="Verbatim sentence from the evidence supporting the value.",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)


_MODEL_CACHE: dict[str, type[BaseModel]] = {}


def family_extraction_model(family: FactFamily) -> type[BaseModel]:
    """Un schéma Pydantic par famille : le LLM ne voit que les champs qu'il doit remplir."""
    if family.name not in _MODEL_CACHE:
        class_name = "".join(part.capitalize() for part in family.name.split("_")) + "Extraction"
        _MODEL_CACHE[family.name] = create_model(
            class_name,
            **{
                field.name: (FieldExtraction, Field(default_factory=FieldExtraction))
                for field in family.fields
            },
        )
    return _MODEL_CACHE[family.name]


def _select_evidence_text(
    text: str, keywords: tuple[str, ...], max_chars: int = _MAX_FAMILY_EVIDENCE_CHARS,
) -> str:
    """Ne garde que les extraits pertinents pour CETTE famille quand l'évidence déborde.

    Sur le chemin Tavily l'évidence d'une famille tient presque toujours dans le
    budget ; sur le chemin de repli `fetch_terms` (une page de CGU entière), ce
    découpage est ce qui rend le prompt exploitable.
    """
    if len(text) <= max_chars:
        return text

    excerpts: list[str] = []
    seen: set[str] = set()
    used = 0

    def add_excerpt(excerpt: str, limit: int = max_chars) -> None:
        nonlocal used
        excerpt = excerpt.strip()
        if not excerpt or excerpt in seen or used >= limit:
            return
        remaining = limit - used
        if len(excerpt) > remaining:
            excerpt = excerpt[:remaining].rstrip()
        excerpts.append(excerpt)
        seen.add(excerpt)
        used += len(excerpt) + 7

    heading_budget = max_chars // 10
    for source in text.split(_SOURCE_SEPARATOR):
        if used >= heading_budget:
            break
        add_excerpt(source[:350], heading_budget)

    for pattern in keywords:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - 250)
            end = min(len(text), match.end() + 500)
            add_excerpt(text[start:end])
            break
        if used >= max_chars:
            break

    return "\n\n...\n\n".join(excerpts) if excerpts else text[:max_chars]


def _build_family_prompt(family: FactFamily, text: str) -> str:
    lines = [
        "Required JSON keys. Each key maps to an object "
        '{"value": ..., "source_url": ..., "quote": ..., "confidence": 0..1}.',
    ]
    for field in family.fields:
        lines.append(f"- {field.name}: {' | '.join(field.allowed_values)} — {field.hint}")
    lines.append(
        "Include every key even when unknown. `quote` must be copied verbatim from "
        "the evidence; without a quote, answer unknown."
    )
    lines.append("")
    lines.append("Evidence:")
    lines.append(_select_evidence_text(text, family.keywords))
    return "\n".join(lines)


def _accept(field: FactField, raw: FieldExtraction) -> FactEvidence:
    """Aucune valeur n'entre dans ContractFacts sans citation vérifiable."""
    value = raw.value if raw.value in field.allowed_values else "unknown"
    quote = (raw.quote or "").strip()[:_MAX_QUOTE_CHARS]

    if value == "unknown":
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote or None,
            confidence=raw.confidence,
        )
    if not quote or not raw.source_url:
        return FactEvidence(
            value="unknown", confidence=0.0,
            note="valeur écartée: aucune citation vérifiable",
        )
    return FactEvidence(
        value=value, source_url=raw.source_url, quote=quote, confidence=raw.confidence,
    )


def _unresolved(family: FactFamily, note: str) -> dict[str, FactEvidence]:
    return {
        field.name: FactEvidence(value="unknown", note=note) for field in family.fields
    }


def _extract_family(
    family: FactFamily, evidence: ContractEvidence, llm: LLMProvider,
) -> dict[str, FactEvidence]:
    if family.name in evidence.failed_families:
        return _unresolved(family, "collecte Tavily échouée")
    terms = evidence.by_family.get(family.name)
    if terms is None:
        return _unresolved(family, "aucune évidence collectée")

    with trace_step(None, "arp_family_extraction", family=family.name) as extra:
        try:
            extracted = llm.complete_structured(
                _SYSTEM,
                _build_family_prompt(family, terms.text),
                family_extraction_model(family),
                run_name=f"extract_contract_facts:{family.name}",
                tags=["arp_extraction", family.name],
            )
        except Exception as exc:  # noqa: BLE001 — une famille perdue ne doit pas tuer l'entrevue
            extra["outcome"] = "failed"
            extra["error"] = type(exc).__name__
            return _unresolved(family, "extraction LLM échouée")
        extra["outcome"] = "ok"

    return {
        field.name: _accept(field, getattr(extracted, field.name))
        for field in family.fields
    }


def extract_contract_facts(evidence: ContractEvidence, llm: LLMProvider) -> ContractFacts:
    proofs: dict[str, FactEvidence] = {}
    for family in FACT_FAMILIES:
        proofs.update(_extract_family(family, evidence, llm))

    values = {name: proof.value for name, proof in proofs.items()}
    confidences = [proof.confidence for proof in proofs.values() if proof.value != "unknown"]
    primary = evidence.primary_source_url()
    fetched_at = next(
        (terms.fetched_at for terms in evidence.by_family.values()), None,
    )

    return ContractFacts(
        **values,
        evidence=proofs,
        source_url=primary,
        fetched_at=fetched_at,
        extraction_confidence=round(mean(confidences), 2) if confidences else 0.0,
    )
```

Supprimer `_require_non_empty_extraction` : la règle « pas de valeur sans citation » la remplace — un LLM qui rend un objet vide produit désormais 16 `unknown` annotés, ce qui est le comportement voulu, pas une erreur à lever.

Ajuster les imports en tête de `arp.py` : garder `re`, remplacer `from typing import Literal` par `from typing import Optional` (`Literal` n'est plus utilisé, `Optional` l'est par `FieldExtraction`).

- [ ] **Step 5 : Lancer les tests**

Run: `pytest tests/contract/test_arp_extraction.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6 : Commit**

```bash
git add policybot/contract/arp.py tests/contract/test_arp_extraction.py tests/helpers/
git commit -m "feat(arp): extraction LLM par famille, chaque fait cite sa source"
```

---

### Task 6 : Observations sourcées et câblage de l'orchestrateur

**Files:**
- Modify: `policybot/contract/arp.py` (`build_arp`, lignes 249-319 avant Task 5)
- Modify: `policybot/interview/orchestrator.py:36-80`
- Modify: `tests/contract/test_arp.py`, `tests/interview/test_orchestrator.py`, `tests/interview/test_graph.py`, `tests/api/test_app.py`, `tests/web/test_routes_resultat.py`, `tests/report/test_renderer.py`, `tests/test_golden_scenarios.py`, `tests/test_tracing.py`
- Test: `tests/contract/test_arp_observations.py` *(créé)*

**Interfaces:**
- Consumes: `ContractFacts.evidence` (Task 1), `extract_contract_facts(evidence, llm)` (Task 5), `ContractEvidence.from_single` (Task 1).
- Produces:
  - `build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord` — signature inchangée ; les `observations` de chaque `RiskFactor` gagnent la source et la citation quand elles existent.
  - `Interview.__init__(..., tavily_search: Optional[Callable[[str], ContractEvidence | None]] = None)` — **le callable rend désormais un `ContractEvidence`**, plus un `FetchedTerms`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/contract/test_arp_observations.py` :

```python
from datetime import date

from policybot.contract.arp import build_arp
from policybot.models import ContractFacts, FactEvidence


def _facts(**overrides) -> ContractFacts:
    return ContractFacts(
        trains_on_input="no",
        evidence={"trains_on_input": FactEvidence(
            value="no",
            source_url="https://example.test/terms",
            quote="We do not train our models on your business data.",
            confidence=0.9,
        )},
        source_url="https://example.test/terms",
        fetched_at=date(2026, 7, 14),
        **overrides,
    )


def _criterion(arp, name):
    return next(factor for factor in arp.criteria if factor.criterion == name)


def test_observations_cite_the_url_and_the_quote():
    arp = build_arp("ChatGPT", "publique", _facts())

    observations = _criterion(
        arp, "Données soumises utilisées pour entraînement du modèle",
    ).observations

    assert observations.startswith("trains_on_input=no")
    assert "https://example.test/terms" in observations
    assert "We do not train our models" in observations


def test_a_fact_without_evidence_keeps_the_bare_observation():
    arp = build_arp("ChatGPT", "publique", _facts())

    observations = _criterion(arp, "Juridiction applicable").observations

    assert observations == "applicable_law=unknown"


def test_an_annotated_unknown_explains_itself_to_the_officer():
    facts = ContractFacts(evidence={"applicable_law": FactEvidence(
        value="unknown", note="collecte Tavily échouée",
    )})

    arp = build_arp("ChatGPT", "publique", facts)

    observations = _criterion(arp, "Juridiction applicable").observations
    assert observations == "applicable_law=unknown — collecte Tavily échouée"
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_arp_observations.py -v`
Expected: FAIL — `assert 'https://example.test/terms' in 'trains_on_input=no'`

- [ ] **Step 3 : Ajouter le rendu des observations dans `policybot/contract/arp.py`**

Insérer avant `build_arp` :

```python
def _observation(facts: ContractFacts, field_name: str) -> str:
    """La ligne que l'officier lit dans le rapport : la valeur, sa source, sa preuve."""
    base = f"{field_name}={getattr(facts, field_name)}"
    proof = facts.evidence.get(field_name)
    if proof is None:
        return base
    if proof.note:
        return f"{base} — {proof.note}"
    parts = [base]
    if proof.quote:
        parts.append(f"« {proof.quote} »")
    if proof.source_url:
        parts.append(f"source: {proof.source_url}")
    return " — ".join(parts)
```

Puis, dans `build_arp`, remplacer chacun des huit `observations=f"champ={facts.champ}"` par `observations=_observation(facts, "champ")`. Exemple pour le premier :

```python
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=_observation(facts, "data_residency"),
    ))
```

Les huit champs concernés : `data_residency`, `applicable_law`, `foreign_vendor_dependency`, `trains_on_input`, `contract_prohibits_reuse`, `encryption_standard`, `reentraining_opt_out`, `ip_ownership`.

- [ ] **Step 4 : Câbler l'orchestrateur (`policybot/interview/orchestrator.py`)**

Remplacer le corps de `_resolve_arp` (lignes 60-77) :

```python
            with trace_step(None, "resolve_arp_fetch", tool_name=tool_name) as fetch_extra:
                evidence = None
                if self._tavily_search is not None:
                    evidence = self._tavily_search(tool_name)
                    fetch_extra["source"] = "tavily" if evidence is not None else "tavily_miss"
                elif os.environ.get("POLICYBOT_CONTRACT_SEARCH", "").strip().lower() == "tavily":
                    from policybot.contract.tavily import search_contract_terms_with_tavily

                    evidence = search_contract_terms_with_tavily(tool_name)
                    fetch_extra["source"] = "tavily" if evidence is not None else "tavily_miss"
                if evidence is None:
                    terms = fetch_terms(tool_name, http_get=self._http_get)
                    fetch_extra.setdefault("source", "direct_terms")
                    evidence = (
                        ContractEvidence.from_single(terms) if terms is not None else None
                    )
                fetch_extra["found"] = evidence is not None
                if evidence is None:
                    facts = ContractFacts()  # manual-paste fallback handled by the UI layer
                else:
                    fetch_extra["families"] = len(evidence.by_family)
                    facts = extract_contract_facts(evidence, self._llm)
```

Mettre à jour l'import (`from policybot.contract.evidence import ContractEvidence`) et l'annotation du constructeur :

```python
    def __init__(self, llm: LLMProvider, store: PreApprovedStore,
                 http_get: Optional[Callable[[str], str]] = None,
                 tavily_search: Optional[Callable[[str], "ContractEvidence | None"]] = None):
```

- [ ] **Step 5 : Migrer les tests qui alimentent l'extraction ARP**

Huit fichiers passent aujourd'hui un dict plat de faits au `FakeLLMProvider`. Dans chacun, remplacer ce dict par un dépliage du helper. Exemple, dans `tests/interview/test_orchestrator.py` :

```python
from tests.helpers.arp_fixtures import arp_extraction_responses

llm = FakeLLMProvider(json_responses=[
    {"already_public": True, "contains_personal_info": False,
     "strategic_sensitive": False, "internal_nonpublic": False,
     "highly_sensitive_secret": False, "confidence": 0.9},
    *arp_extraction_responses(
        trains_on_input="no", data_retention="none", data_residency="canada",
        sub_processors="disclosed", human_review="yes",
        encryption_standard="strong", ip_ownership="customer",
    ),
])
```

Règle mécanique : partout où une réponse de classification est suivie d'un dict de faits contractuels, remplacer ce dict par `*arp_extraction_responses(**ces_mêmes_faits)`. L'ordre compte — la classification des données passe avant l'extraction ARP dans la file du `FakeLLMProvider`. Fichiers à migrer : `tests/contract/test_arp.py`, `tests/interview/test_orchestrator.py`, `tests/interview/test_graph.py`, `tests/api/test_app.py`, `tests/web/test_routes_resultat.py`, `tests/report/test_renderer.py`, `tests/test_golden_scenarios.py`, `tests/test_tracing.py`.

Dans `tests/contract/test_arp.py`, les appels directs à `extract_contract_facts(terms, llm)` deviennent `extract_contract_facts(ContractEvidence.from_single(terms), llm)`.

Dans `tests/contract/test_tavily_errors.py`, adapter `test_interview_uses_injected_tavily_terms_before_direct_fetch` (déplacé en Task 4) : le `tavily_search` injecté rend maintenant un `ContractEvidence` :

```python
def tavily_search(tool_name):
    assert tool_name == "ChatGPT"
    return ContractEvidence.from_single(FetchedTerms(
        text="Tavily evidence: customer content is not used for training.",
        source_url="https://example.test/tavily",
        fetched_at=date.today(),
    ))
```

et la file du `FakeLLMProvider` devient `[classification, *arp_extraction_responses(trains_on_input="no")]`.

- [ ] **Step 6 : Lancer toute la suite**

Run: `pytest -q`
Expected: PASS — aucun test en échec, aucun `skipped` restant de la Task 2.

- [ ] **Step 7 : Vérifier que le rapport affiche bien les citations**

Run: `pytest tests/report -v`
Expected: PASS. Le gabarit `policybot/report/templates/report.html.j2` rend déjà `factor.observations` : la citation et l'URL apparaissent sans modification du gabarit. Si un test du rapport asserte une observation exacte (`"data_residency=canada"`), le mettre à jour pour accepter le suffixe sourcé.

- [ ] **Step 8 : Commit**

```bash
git add policybot/contract/arp.py policybot/interview/orchestrator.py tests/
git commit -m "feat(arp): observations sourcées, orchestrateur câblé sur ContractEvidence"
```

---

### Task 7 : CLI probe, documentation, vérification finale

**Files:**
- Modify: `policybot/contract/tavily_probe.py:86-124`
- Modify: `tests/contract/test_tavily_probe.py`
- Modify: `CLAUDE.md` (sections « Pipeline » étape 2 et « Package layout »)
- Modify: `HOW_TO_RUN.md:40-60`

**Interfaces:**
- Consumes: `search_contract_terms_with_tavily -> ContractEvidence | None` (Task 4), `extract_contract_facts(evidence, llm)` (Task 5).
- Produces: rien de nouveau — le CLI reste `python -m policybot.contract.tavily_probe "<outil>" [--facts] [--arp]`.

- [ ] **Step 1 : Mettre à jour le test du probe**

Dans `tests/contract/test_tavily_probe.py`, le double de `search_contract_terms_with_tavily` doit rendre un `ContractEvidence` :

```python
from datetime import date

from policybot.contract.evidence import ContractEvidence
from policybot.contract.fetcher import FetchedTerms
from policybot.contract import tavily_probe


def test_probe_requires_tavily_evidence(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tavily_probe, "search_contract_terms_with_tavily", lambda *a, **k: None,
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    assert code == 2
    assert "Aucune evidence Tavily" in capsys.readouterr().err


def test_probe_reports_evidence_per_family(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tavily_probe,
        "search_contract_terms_with_tavily",
        lambda *a, **k: ContractEvidence.from_single(FetchedTerms(
            text="Evidence from Tavily Extract",
            source_url="https://example.test/terms",
            fetched_at=date(2026, 7, 14),
        )),
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "https://example.test/terms" in out
    assert "entrainement_reutilisation" in out
    assert "Evidence from Tavily Extract" in out
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `pytest tests/contract/test_tavily_probe.py -v`
Expected: FAIL — le probe lit `terms.text` sur un `ContractEvidence` (`AttributeError`).

- [ ] **Step 3 : Adapter `policybot/contract/tavily_probe.py`**

Remplacer les lignes 86-124 par :

```python
    evidence = search_contract_terms_with_tavily(args.tool_name, config_dir=args.config_dir)
    if evidence is None:
        print(
            "Aucune evidence Tavily trouvee. Verifie TAVILY_API_KEY et la config YAML.",
            file=sys.stderr,
        )
        return 2

    if args.evidence_out:
        _write_text(args.evidence_out, "\n\n=====\n\n".join(
            f"[{name}] {terms.source_url}\n{terms.text}"
            for name, terms in evidence.by_family.items()
        ))

    result: dict = {
        "tool_name": args.tool_name,
        "config_path": str(config_path),
        "source_url": evidence.primary_source_url(),
        "failed_families": list(evidence.failed_families),
        "families": {
            name: {
                "source_url": terms.source_url,
                "fetched_at": terms.fetched_at.isoformat(),
                "evidence_chars": len(terms.text),
                "evidence_preview": terms.text[:400],
            }
            for name, terms in evidence.by_family.items()
        },
    }
    if args.evidence_out:
        result["evidence_out"] = args.evidence_out

    if args.facts:
        import os

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print(
                "--facts requiert OPENROUTER_API_KEY dans l'environnement ou .env.",
                file=sys.stderr,
            )
            return 3
        facts = extract_contract_facts(evidence, OpenRouterProvider(api_key))
        result["contract_facts"] = facts.model_dump(mode="json")
        if args.arp:
            arp = build_arp(args.tool_name, args.iag_type, facts)
            result["arp"] = arp.model_dump(mode="json")

    _print_yaml(result)
    return 0
```

- [ ] **Step 4 : Lancer les tests**

Run: `pytest tests/contract/test_tavily_probe.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5 : Mettre à jour `CLAUDE.md`**

Dans « Pipeline », étape 2, remplacer la description de la source Tavily par : « via `policybot/contract/tavily.py` (une recherche Tavily par **famille de critères** — 5 familles définies dans `contract/families.py` —, un seul Extract sur les URLs dédupliquées avec budget réparti en round-robin, config auto-générée par outil sous `configs/tavily_contracts/`) — puis une extraction LLM **par famille**, chaque fait revenant avec sa valeur, son URL et une citation verbatim (`ContractFacts.evidence`). Un fait sans citation retombe à `unknown`. Une erreur Tavily dégrade la famille concernée, jamais l'entrevue. »

Dans « Package layout », sous `contract/`, ajouter : « `families.py` (les 5 familles de critères : requête, champs, mots-clés), `evidence.py` (`ContractEvidence` : l'évidence indexée par famille) ».

- [ ] **Step 6 : Mettre à jour `HOW_TO_RUN.md`**

Dans la section « Recherche contractuelle Tavily », corriger le décompte : « 5 recherches ciblées, une par famille de critères » remplace « 16 requêtes ciblées, une par fait contractuel ». Corriger la même phrase dans `.env.example:7`.

- [ ] **Step 7 : Vérification finale**

Run: `pytest -q`
Expected: PASS, aucun `skipped`.

Run: `python -c "from policybot.contract.tavily import build_contract_search_config as b; c=b('ChatGPT'); print(len(c['families']), sum(len(f['fields']) for f in c['families']))"`
Expected: `5 16`

- [ ] **Step 8 : Commit**

```bash
git add policybot/contract/tavily_probe.py tests/contract/test_tavily_probe.py CLAUDE.md HOW_TO_RUN.md .env.example
git commit -m "docs: probe, CLAUDE.md et HOW_TO_RUN alignés sur la collecte par familles"
```
