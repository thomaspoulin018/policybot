"""Harnais manuel d'évaluation de l'extraction des faits contractuels.

Les cas golden contiennent une preuve figée et une vérité terrain relue à la
main. Ce module reste volontairement hors de la suite d'évaluation en ligne :
ses fonctions sont testables avec ``FakeLLMProvider``, tandis que son point
d'entrée utilise le fournisseur OpenRouter configuré pour la production.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

import yaml
from dotenv import load_dotenv

from policybot.config import load_config
from policybot.contract.arp import extract_contract_facts
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import ALL_FACT_FIELDS
from policybot.contract.fetcher import FetchedTerms
from policybot.contract.offering import build_offering_identity
from policybot.classify.tool_registry import lookup_tool
from policybot.contract.tavily import search_contract_terms_with_tavily
from policybot.llm.openrouter import OpenRouterProvider
from policybot.llm.provider import LLMProvider
from policybot.models import ContractFacts, ContractOfferingIdentity, FactEvidence


DEFAULT_GOLDEN_ROOT = (
    Path(__file__).resolve().parents[2] / "tests" / "contract" / "fixtures" / "golden"
)
_FACT_FIELDS_BY_NAME = {field.name: field for field in ALL_FACT_FIELDS}
_REQUIRED_HEADERS = ("source", "fetched_at")
_TOOL_NAMES = {
    "chatgpt": "ChatGPT",
    "claude_ai": "Claude.ai",
    "microsoft_copilot_entreprise": "Microsoft Copilot Entreprise",
}


@dataclass(frozen=True)
class GoldenCase:
    tool_slug: str
    evidence: ContractEvidence
    expected: dict[str, str]
    offering: ContractOfferingIdentity | None = None


class Verdict(str, Enum):
    MATCH = "MATCH"
    WRONG_VALUE = "WRONG_VALUE"
    WRONG_ABSTAIN = "WRONG_ABSTAIN"


class MetricCategory(str, Enum):
    COLLECTION_FAILURE = "COLLECTION_FAILURE"
    FACT_ABSENT = "FACT_ABSENT"
    LLM_FAILURE = "LLM_FAILURE"
    MODEL_ABSTENTION = "MODEL_ABSTENTION"
    CITATION_REJECTED = "CITATION_REJECTED"
    INCORRECT_VALUE = "INCORRECT_VALUE"
    FALSE_REASSURING = "FALSE_REASSURING"


@dataclass(frozen=True)
class FieldResult:
    field: str
    expected: str
    got: str
    verdict: Verdict
    metrics: tuple[MetricCategory, ...] = ()


_RISK_RANKS: dict[str, dict[str, int]] = {
    "training_default": {"no": 0, "yes": 2, "unknown": 3},
    "opt_out_available": {"yes": 1, "no": 2, "unknown": 3},
    "opt_out_confirmed_enabled": {"yes": 0, "no": 2, "unknown": 3},
    "data_retention": {"none": 0, "limited": 1, "indefinite": 2, "unknown": 3},
    "data_residency": {
        "quebec": 0, "canada_outside_quebec": 1, "us": 2, "eu": 2,
        "multi_region": 3, "configurable": 3, "unknown": 3,
    },
    "sub_processors": {"disclosed": 0, "undisclosed": 2, "unknown": 3},
    "provider_human_access": {"no": 0, "yes": 2, "unknown": 3},
    "encryption_standard": {"strong": 0, "partial": 1, "none": 2, "unknown": 3},
    "ip_ownership": {"customer": 0, "unclear": 1, "vendor": 2, "unknown": 3},
    "contract_prohibits_reuse": {"yes": 0, "no": 2, "unknown": 3},
    "authentication_support": {"sso_mfa": 0, "partial": 1, "none": 2, "unknown": 3},
    "audit_logging": {"prompt_output_accessible": 0, "access_logs_only": 1, "none": 2, "unknown": 3},
    "institutional_terms_available": {"yes": 0, "no": 2, "unknown": 3},
    "dpa_available": {"yes": 0, "no": 2, "unknown": 3},
    "institutional_use_restricted": {"no": 0, "yes": 2, "unknown": 3},
    "quebec_higher_ed_license": {"yes": 0, "no": 2, "unknown": 3},
    "incident_response": {"documented_with_notice": 0, "documented_no_notice": 1, "none": 2, "unknown": 3},
    "applicable_law": {"quebec_canada": 0, "foreign": 2, "unknown": 3},
    "foreign_vendor_dependency": {"no": 0, "yes": 2, "unknown": 3},
}

_OUTCOME_METRICS = {
    "collection_failure": MetricCategory.COLLECTION_FAILURE,
    "evidence_missing": MetricCategory.FACT_ABSENT,
    "llm_failure": MetricCategory.LLM_FAILURE,
    "model_abstention": MetricCategory.MODEL_ABSTENTION,
    "citation_rejected": MetricCategory.CITATION_REJECTED,
    "invalid_value": MetricCategory.CITATION_REJECTED,
}


def _is_false_reassuring(field: str, expected: str, got: str) -> bool:
    ranks = _RISK_RANKS.get(field)
    if ranks is None or expected not in ranks or got not in ranks:
        return False
    return ranks[got] < ranks[expected]


def _field_metrics(
    field: str,
    expected: str,
    extracted: FactEvidence,
    verdict: Verdict,
) -> tuple[MetricCategory, ...]:
    outcome_metric = _OUTCOME_METRICS.get(extracted.outcome or "")
    if outcome_metric is not None and extracted.value == "unknown":
        return (outcome_metric,)
    if verdict is Verdict.WRONG_ABSTAIN:
        return (MetricCategory.MODEL_ABSTENTION,)
    if verdict is Verdict.WRONG_VALUE:
        metrics = [MetricCategory.INCORRECT_VALUE]
        if _is_false_reassuring(field, expected, extracted.value):
            metrics.append(MetricCategory.FALSE_REASSURING)
        return tuple(metrics)
    return ()


class RecordingTavilyClient:
    """Décorateur Tavily qui conserve les requêtes et réponses brutes rejouables."""

    def __init__(self, client: Any):
        self._client = client
        self.calls: dict[str, list[dict[str, Any]]] = {"search": [], "extract": []}

    def search(self, *, query: str, **kwargs: Any) -> object:
        call: dict[str, Any] = {"query": query, "kwargs": kwargs}
        try:
            response = self._client.search(query=query, **kwargs)
        except Exception as exc:
            call["error"] = {"type": type(exc).__name__, "message": str(exc)}
            self.calls["search"].append(call)
            raise
        call["response"] = response
        self.calls["search"].append(call)
        return response

    def extract(self, urls: list[str], **kwargs: Any) -> object:
        call: dict[str, Any] = {"urls": list(urls), "kwargs": kwargs}
        try:
            response = self._client.extract(urls, **kwargs)
        except Exception as exc:
            call["error"] = {"type": type(exc).__name__, "message": str(exc)}
            self.calls["extract"].append(call)
            raise
        call["response"] = response
        self.calls["extract"].append(call)
        return response


class SnapshotTavilyClient:
    """Client sans réseau qui rejoue strictement un snapshot Tavily brut."""

    def __init__(self, snapshot: dict[str, Any]):
        calls = snapshot.get("calls") or {}
        self._search = iter(calls.get("search") or [])
        self._extract = iter(calls.get("extract") or [])

    @staticmethod
    def _replay(call: dict[str, Any], expected: dict[str, Any]) -> object:
        for key, value in expected.items():
            if call.get(key) != value:
                raise ValueError(
                    f"Snapshot Tavily incompatible pour {key}: "
                    f"attendu={call.get(key)!r}, reçu={value!r}"
                )
        if "error" in call:
            error = call["error"]
            raise RuntimeError(
                f"Échec Tavily rejoué: {error.get('type', 'Error')}: "
                f"{error.get('message', '')}"
            )
        return call.get("response", {})

    def search(self, *, query: str, **kwargs: Any) -> object:
        try:
            call = next(self._search)
        except StopIteration as exc:
            raise ValueError("Snapshot Tavily épuisé pendant Search") from exc
        return self._replay(call, {"query": query, "kwargs": kwargs})

    def extract(self, urls: list[str], **kwargs: Any) -> object:
        try:
            call = next(self._extract)
        except StopIteration as exc:
            raise ValueError("Snapshot Tavily épuisé pendant Extract") from exc
        return self._replay(call, {"urls": list(urls), "kwargs": kwargs})


def _parse_evidence_file(path: Path) -> list[FetchedTerms]:
    """Charge les documents figés d'un cas golden, sans fusionner leurs URL.

    Les anciens golden regroupaient plusieurs pages derrière l'URL déclarée dans
    l'en-tête du fichier. Cela ne permettait pas de reproduire le contrôle
    production qui exige qu'une citation soit présente dans *l'URL citée*.
    Chaque bloc ``URL:`` devient maintenant un document distinct. Un ancien
    fichier sans bloc reste lisible comme une preuve mono-document.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    headers: dict[str, str] = {}
    body_start = 0
    for index, line in enumerate(lines):
        if not line.startswith("#"):
            body_start = index
            break
        key, separator, value = line[1:].partition(":")
        if not separator:
            raise ValueError(f"Invalid evidence header in {path}: {line!r}")
        headers[key.strip()] = value.strip()
        body_start = index + 1

    missing = [name for name in _REQUIRED_HEADERS if not headers.get(name)]
    if missing:
        raise ValueError(f"Missing evidence header(s) in {path}: {', '.join(missing)}")

    try:
        fetched_at = date.fromisoformat(headers["fetched_at"])
    except ValueError as exc:
        raise ValueError(
            f"Invalid fetched_at date in {path}: {headers['fetched_at']!r}"
        ) from exc

    body = lines[body_start:]
    if not any(line.strip() for line in body):
        raise ValueError(f"Evidence body is empty: {path}")

    documents: list[FetchedTerms] = []
    current_url: str | None = None
    current_lines: list[str] = []

    def add_document() -> None:
        nonlocal current_url, current_lines
        if current_url is None:
            return
        content = "\n".join(current_lines).strip()
        if not content:
            raise ValueError(f"Evidence document is empty for {current_url} in {path}")
        documents.append(FetchedTerms(
            text=content, source_url=current_url, fetched_at=fetched_at,
        ))
        current_lines = []

    for line in body:
        if line.startswith("URL: "):
            add_document()
            current_url = line.removeprefix("URL: ").strip()
            if not current_url:
                raise ValueError(f"Evidence URL is empty in {path}")
            continue
        if current_url is not None:
            current_lines.append(line)
        elif line.strip():
            # Compatibilité des anciennes fixtures mono-document.
            current_lines.append(line)

    add_document()
    if documents:
        return documents

    text = "\n".join(current_lines).strip()
    if not text:
        raise ValueError(f"Evidence body is empty: {path}")
    return [FetchedTerms(text=text, source_url=headers["source"], fetched_at=fetched_at)]


def _load_offering(case_dir: Path, tool_name: str) -> ContractOfferingIdentity:
    """Charge l'identité contractuelle explicite d'une fixture si elle existe."""
    path = case_dir / "offering.yaml"
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Offering identity must be a YAML mapping: {path}")
        return ContractOfferingIdentity.model_validate(raw)

    entry = lookup_tool(tool_name) or {}
    return build_offering_identity(
        tool_name, entry.get("iag_type") or "publique",
        vendor=entry.get("vendor"),
    )


def _load_expected(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected values must be a YAML mapping: {path}")

    expected: dict[str, str] = {}
    for field_name, value in raw.items():
        if not isinstance(field_name, str) or field_name not in _FACT_FIELDS_BY_NAME:
            raise ValueError(f"Unknown ContractFacts field in {path}: {field_name!r}")
        # PyYAML suit encore le schéma YAML 1.1 pour ``yes``/``no`` et les
        # transforme en booléens. Ces deux lexèmes sont précisément des valeurs
        # normalisées de ContractFacts, donc on les rétablit sans obliger les
        # annotateurs à connaître ce piège de syntaxe YAML.
        if isinstance(value, bool):
            value = "yes" if value else "no"
        if not isinstance(value, str):
            raise ValueError(
                f"Expected value for {field_name!r} must be a string in {path}"
            )
        expected[field_name] = value
    return expected


def load_golden_case(case_dir: str | Path) -> GoldenCase:
    """Charge un dossier ``evidence.txt`` + ``expected.yaml``."""
    directory = Path(case_dir)
    terms = _parse_evidence_file(directory / "evidence.txt")
    expected = _load_expected(directory / "expected.yaml")
    tool_name = _TOOL_NAMES.get(directory.name, directory.name.replace("_", " "))
    return GoldenCase(
        tool_slug=directory.name,
        evidence=ContractEvidence.from_terms(terms),
        expected=expected,
        offering=_load_offering(directory, tool_name),
    )


def discover_golden_cases(root: str | Path = DEFAULT_GOLDEN_ROOT) -> list[GoldenCase]:
    """Découvre les cas golden dans un ordre stable."""
    golden_root = Path(root)
    if not golden_root.is_dir():
        return []
    return [
        load_golden_case(case_dir)
        for case_dir in sorted(path for path in golden_root.iterdir() if path.is_dir())
    ]


def _snapshot_path(run_dir: Path, tool_slug: str) -> Path:
    return run_dir / "snapshots" / f"{tool_slug}.json"


def _write_snapshot(
    run_dir: Path,
    case: GoldenCase,
    tool_name: str,
    recorder: RecordingTavilyClient,
) -> None:
    path = _snapshot_path(run_dir, case.tool_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "tool_slug": case.tool_slug,
        "tool_name": tool_name,
        "calls": recorder.calls,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def collect_cases(
    cases: list[GoldenCase],
    *,
    source: str,
    run_dir: str | Path,
    api_key: str | None = None,
    tavily_client: Any | None = None,
) -> list[GoldenCase]:
    """Remplace les preuves golden par une collecte Tavily live ou rejouée."""
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    client = tavily_client
    if source == "live" and client is None:
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY est absent pour --source live.")
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)

    collected: list[GoldenCase] = []
    try:
        for case in cases:
            tool_name = _TOOL_NAMES.get(case.tool_slug, case.tool_slug.replace("_", " "))
            if source == "live":
                recorder = RecordingTavilyClient(client)
                evidence = search_contract_terms_with_tavily(
                    tool_name, offering=case.offering, client=recorder,
                )
                _write_snapshot(directory, case, tool_name, recorder)
            elif source == "snapshot":
                path = _snapshot_path(directory, case.tool_slug)
                if not path.is_file():
                    raise FileNotFoundError(f"Snapshot Tavily absent: {path}")
                payload = json.loads(path.read_text(encoding="utf-8"))
                evidence = search_contract_terms_with_tavily(
                    tool_name,
                    offering=case.offering,
                    client=SnapshotTavilyClient(payload),
                )
            else:
                raise ValueError(f"Source inconnue: {source!r}")
            if evidence is None:
                raise RuntimeError(f"Aucune évidence Tavily collectée pour {tool_name}")
            collected.append(
                GoldenCase(
                    tool_slug=case.tool_slug,
                    evidence=evidence,
                    expected=case.expected,
                    offering=case.offering,
                )
            )
    finally:
        if source == "live" and tavily_client is None and hasattr(client, "close"):
            client.close()
    return collected


def validate_complete_case(case: GoldenCase) -> None:
    """Valide la couverture et le vocabulaire d'une fixture golden réelle."""
    expected_names = set(_FACT_FIELDS_BY_NAME)
    actual_names = set(case.expected)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        raise ValueError(f"Incomplete golden case {case.tool_slug}: {', '.join(details)}")

    for field_name, expected in case.expected.items():
        allowed = _FACT_FIELDS_BY_NAME[field_name].allowed_values
        if expected not in allowed:
            raise ValueError(
                f"Invalid expected value for {case.tool_slug}.{field_name}: "
                f"{expected!r}; allowed={allowed}"
            )


def score_field(expected: str, extracted: FactEvidence) -> Verdict:
    if extracted.value == expected:
        return Verdict.MATCH
    if extracted.value == "unknown" and expected != "unknown":
        return Verdict.WRONG_ABSTAIN
    return Verdict.WRONG_VALUE


def score_case(case: GoldenCase, facts: ContractFacts) -> list[FieldResult]:
    results: list[FieldResult] = []
    for field_name, expected in case.expected.items():
        extracted = facts.evidence.get(
            field_name,
            FactEvidence(value=getattr(facts, field_name)),
        )
        results.append(
            FieldResult(
                field=field_name,
                expected=expected,
                got=extracted.value,
                verdict=(verdict := score_field(expected, extracted)),
                metrics=_field_metrics(field_name, expected, extracted, verdict),
            )
        )
    return results


def has_wrong_value(results: dict[str, list[FieldResult]]) -> bool:
    return any(
        result.verdict is Verdict.WRONG_VALUE
        for case_results in results.values()
        for result in case_results
    )


def format_report(results: dict[str, list[FieldResult]]) -> str:
    lines = ["Extraction ARP — rapport du jeu d'évaluation", ""]
    counts = {verdict: 0 for verdict in Verdict}
    metric_counts = {metric: 0 for metric in MetricCategory}

    for tool_slug, case_results in results.items():
        lines.extend(
            [
                f"## {tool_slug}",
                "field | expected | got | verdict | metrics",
                "--- | --- | --- | --- | ---",
            ]
        )
        for result in case_results:
            counts[result.verdict] += 1
            for metric in result.metrics:
                metric_counts[metric] += 1
            lines.append(
                f"{result.field} | {result.expected} | {result.got} | "
                f"{result.verdict.value} | "
                f"{', '.join(metric.value for metric in result.metrics)}"
            )
        lines.append("")

    total = sum(counts.values())
    wrong_value_rate = (counts[Verdict.WRONG_VALUE] / total * 100) if total else 0.0
    lines.extend(
        [
            "## Résumé agrégé",
            f"MATCH: {counts[Verdict.MATCH]}",
            f"WRONG_ABSTAIN: {counts[Verdict.WRONG_ABSTAIN]}",
            f"WRONG_VALUE: {counts[Verdict.WRONG_VALUE]}",
            f"**Taux WRONG_VALUE: {wrong_value_rate:.1f}%**",
            "",
            "## Métriques par cause",
            *[
                f"{metric.value}: {metric_counts[metric]}"
                for metric in MetricCategory
            ],
        ]
    )
    return "\n".join(lines)


def main(
    llm: LLMProvider,
    cases: list[GoldenCase],
    *,
    output: TextIO | None = None,
) -> int:
    """Exécute l'évaluation; retourne 1 seulement en présence de WRONG_VALUE."""
    stream = output or sys.stdout
    results: dict[str, list[FieldResult]] = {}
    for case in cases:
        validate_complete_case(case)
        facts = extract_contract_facts(case.evidence, llm)
        results[case.tool_slug] = score_case(case, facts)
    print(format_report(results), file=stream)
    return int(has_wrong_value(results))


def _real_provider() -> OpenRouterProvider:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY est absent. Ajoutez-le dans l'environnement ou .env."
        )
    task_config = load_config().llm.tasks.contract_extraction
    return OpenRouterProvider(
        api_key,
        model=task_config.model,
        reasoning_effort=task_config.reasoning_effort,
        max_tokens=task_config.max_tokens,
        temperature=task_config.temperature,
        timeout=task_config.timeout,
    )


def cli() -> int:
    load_dotenv()
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--source", choices=("live", "snapshot"), default="snapshot",
            help="Collecte Tavily réelle ou rejeu des réponses brutes enregistrées.",
        )
        parser.add_argument(
            "--run-dir", type=Path, required=True,
            help="Dossier contenant snapshots/ et les artefacts du run.",
        )
        args = parser.parse_args()
        llm = _real_provider()
        cases = discover_golden_cases()
        if not cases:
            raise RuntimeError(f"Aucun cas golden trouvé dans {DEFAULT_GOLDEN_ROOT}")
        cases = collect_cases(cases, source=args.source, run_dir=args.run_dir)
        return main(llm, cases)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
