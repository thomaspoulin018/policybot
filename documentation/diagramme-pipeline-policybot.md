# Pipeline PolicyBot — graphe complet

Le trajet réel d'une réponse Google Forms jusqu'aux livrables. Établi par
lecture du code au 12 août 2026, à l'échelle des paquets `policybot/*`.

Conventions : trait plein, chemin nominal ; pointillé, branche conditionnelle
ou effet de bord ; rouge clair, rejet ou échec isolé qui laisse le lot
continuer ; rouge franc, arrêt de tout le lot ; vert, donnée qui circule ;
gris, configuration lue au démarrage ; jaune, main humaine.

Ce qui n'existe plus dans le code et qu'aucun nœud ne doit représenter : le
cache ARP SQLite et `ArpRecord`, `contract/arp.py`, `contract/cache.py`, le
budget de recherche, le module `criteria.py` et ses constantes `ARP_CRITERIA` /
`USAGE_CRITERIA`, le paquet `policybot/llm/` remplacé par le module unique
`policybot/llm.py`, `preapproved/known_tools.py`, le wizard web et son API.

## 1. Vue d'ensemble

Six étapes. Les deux clés d'API sont les seuls points où le lot entier
s'arrête ; tout le reste dégrade une demande ou un critère à la fois.

```mermaid
flowchart LR
  A["Google Forms<br/>créé par l'API"] --> B["responses.list<br/>JSON local"]
  B --> C["intake/<br/>mapping questionId, validation, rejets motivés"]
  C --> D["résolution de l'offre<br/>registre local, aucun réseau"]
  D --> E["classification des données<br/>1 appel OpenRouter"]
  E --> F["17 recherches Exa<br/>8 fils, une par critère recherché"]
  F --> G["fiche .docx + grille .docx + constats .json"]
  G --> H["parties laissées vierges<br/>l'autorité désignée décide"]

  D -.->|"--dry-run"| STOP["arrêt après affichage<br/>aucun appel, aucun coût"]

  classDef ext fill:#ecfeff,stroke:#0891b2,color:#155e75;
  classDef human fill:#fefce8,stroke:#ca8a04,stroke-width:2px,color:#854d0e;
  class A,B ext;
  class H,STOP human;
```

## 2. Entrée, lecture et résolution — `cli.py` + `intake/`

La création et le téléchargement touchent le réseau. L'ingestion reste hors
ligne et rejouable ; une réponse illisible est écartée avec son identifiant et
les autres passent.

```mermaid
flowchart TD

  FYAML[("configs/formulaire.yaml<br/>catalogue de questions")]
  CREATE["google_items.py + google_api.py<br/>create → batchUpdate → publier"]
  FORMS["Google Forms<br/>publié et collecte active"]
  MAP[("configs/formulaire-google.json<br/>questionId → champ")]
  JSON["responses.list → reponses.json"]
  FYAML --> CREATE --> FORMS --> JSON
  CREATE --> MAP

  MAIN["cli.py · main<br/>stdout et stderr reconfigurés en UTF-8<br/>load_dotenv en usage console uniquement"]
  JSON --> MAIN
  MAIN -->|"devis-formulaire"| DEVIS["intake/formulaire.py · devis"]
  DEVIS --> OUT0["aperçu texte hors ligne"]
  MAIN -->|"creer-formulaire"| CREATE
  MAIN -->|"recuperer-reponses"| JSON
  MAIN -->|"ingerer reponses.json"| LIRE

  CREATE -->|"mapping déjà présent<br/>et --force absent"| ABORT0b["FormulaireGoogleExistantError<br/>code de retour 2 · l'URL diffusée est préservée"]

  subgraph SG1["intake/reponses.py · lire_reponses"]
    direction TB
    LIRE["json.loads<br/>responses[] · answers"]
    APP["mapping par questionId stable<br/>jamais par intitulé"]
    CONV["conversion typée par question<br/>texte · nombre · date · oui_non · choix · choix_multiple"]
    VALID["DemandeIAG.model_validate"]
    LOT["LotReponses<br/>demandes · rejets · questionId inconnus<br/>réponses lues"]
    LIRE --> APP --> CONV --> VALID --> LOT
  end

  FYAML -.->|"validé contre DemandeIAG à l'import"| LIRE
  MAP --> APP
  MAIN -->|"fichier introuvable"| ABORT0["FileNotFoundError<br/>code de retour 2"]
  LIRE -->|"JSON illisible ou sans liste responses"| ABORT0c["FichierReponsesInvalideError<br/>code de retour 2"]

  APP -->|"un questionId hors mapping"| REJ0["réponse entière rejetée<br/>identifiant listé dans question_ids_inconnus<br/>le lot continue"]
  CONV -->|"valeur illisible, choix hors liste"| REJ1["ReponseIllisibleError → RejetDemande"]
  VALID -->|"champ obligatoire vide"| REJ2["ValidationError → RejetDemande<br/>le motif ne cite que le nom du champ,<br/>jamais la réponse"]

  LOT --> DEM["DemandeIAG · une réponse = une demande"]

  subgraph SG2["intake/schema.py · vers_entrees_orchestrateur"]
    direction TB
    TYPE["classify_tool_type<br/>sinon tool_type_override"]
    OFFB["contract/offering.py · build_offering_identity<br/>défauts par type IAG,<br/>plan « enterprise / education / team » → managed_saas"]
    NUM["numéro IAG-AAAA-6hex · RequestInfo<br/>usage_inputs = 1 usage · QualificationProfile"]
    TYPE --> OFFB --> NUM
  end

  DEM --> TYPE
  REGI[("classify/tool_registry.py · REGISTRY<br/>5 entrées · vendor + iag_type")]
  REGI --> TYPE
  TYPE -->|"hors registre et aucun type fourni"| REJ3["TypeIagInconnuError<br/>demande écartée, le lot continue"]
  NUM --> ENT["EntreesOrchestrateur<br/>request · tool_name · usage_inputs<br/>iag_type · qualification · offering"]

  ENT --> DRY{"--dry-run ?"}
  DRY -->|"oui"| STOP["identité d'offre affichée,<br/>champs manquants signalés, puis arrêt<br/>aucun appel modèle, aucune recherche, aucun coût"]
  DRY -->|"non"| SUITE(["§3 — assemblage et orchestrateur"])

  classDef conf fill:#f1f5f9,stroke:#94a3b8,color:#334155;
  classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;
  classDef stop fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d;
  classDef ext fill:#ecfeff,stroke:#0891b2,color:#155e75;
  classDef human fill:#fefce8,stroke:#ca8a04,stroke-width:2px,color:#854d0e;
  classDef data fill:#f0fdf4,stroke:#22c55e,color:#166534;

  class FYAML,MAP,REGI conf;
  class REJ0,REJ1,REJ2,REJ3 err;
  class ABORT0,ABORT0b,ABORT0c stop;
  class FORMS,JSON ext;
  class STOP,OUT0 human;
  class LOT,DEM,ENT data;
```

## 3. Assemblage et orchestrateur — `interview/`

La CLI transmet l'offre déjà résolue par `intake/schema.py` en
`offering_override` : l'orchestrateur refait la résolution du type IAG mais
l'override d'identité l'emporte. Il ne reconstruit l'identité que lorsqu'il est
appelé directement, hors CLI.

```mermaid
flowchart TD

  ENT["EntreesOrchestrateur"]

  subgraph SG3["interview/factory.py · default_interview"]
    direction TB
    KEY{"OPENROUTER_API_KEY ?"}
    CONF["load_config · llm.tasks.data_classification<br/>model · reasoning_effort · max_tokens<br/>temperature · timeout"]
    ORP["llm.py · OpenRouterProvider<br/>POST direct, bibliothèque standard"]
    KEY -->|"présente"| CONF --> ORP
  end

  KEY -->|"absente"| ABORT1["CleApiManquante · code de retour 2<br/>arrêt du lot entier · aucun dossier produit<br/>aucun repli FakeLLMProvider silencieux"]
  PYAML[("configs/policybot.yaml<br/>+ surcharges POLICYBOT_LLM_* / OPENROUTER_*")]
  PYAML --> CONF

  subgraph SG4["interview/orchestrator.py · Interview.assess — une demande à la fois"]
    direction TB
    STATE["InterviewState · interview_id uuid4<br/>collect_llm_usage ouvert"]
    RESOL["lookup_tool + classify_tool_type<br/>offering_override prioritaire"]
    TOOLREF["ToolRef ajouté à state.tools"]
    BOUCLE["pour chaque usage_input<br/>la CLI n'en produit qu'un par demande"]
    CLASSD["classify/data_classifier.py · classify_data<br/>seul appel modèle du pipeline"]
    DECID["_decide · arbre déterministe sur les signaux<br/>Protégé C / B / Non classifié / Protégé A<br/>repli conservateur Protégé A si non concluant"]
    USAGE["Usage · classification · rens. personnels<br/>efvpr_required = rens_personnels<br/>confirmation requise si repli ou confiance &lt; 0,6"]
    RECH["_rechercher_constats"]
    FIN["status = complete<br/>audit : llm_usage + search_cost_dollars"]
    STATE --> RESOL --> TOOLREF --> BOUCLE --> CLASSD --> DECID --> USAGE --> RECH
  end

  ENT -->|"cli · default_interview, une fois par lot"| KEY
  ENT --> STATE
  ORP -->|"complete_json · json_object · usage include"| CLASSD
  PROM[("configs/prompts.yaml · prompts.py")] --> CLASSD

  RESOL -->|"aucun type IAG résolu"| ERR1["UnknownToolError"]
  ORP -->|"HTTP hors 2xx, hôte injoignable,<br/>réponse inexploitable"| ERR2["LLMError"]
  ERR1 --> ERRD
  ERR2 --> ERRD
  ERRD["cli · demande en échec<br/>type et message affichés,<br/>le lot continue à la demande suivante"]

  RECH --> EXA(["§4 — 17 recherches Exa"])
  EXA --> VIDE{"liste vide ?"}
  VIDE -->|"oui"| EMPTY["_empty_findings<br/>un constat no_answer par critère recherché"]
  VIDE -->|"non"| TOOLF
  EMPTY --> TOOLF["ToolRef.findings<br/>total_cost_dollars calculé à la volée"]
  TOOLF --> FIN
  FIN --> RENDU(["§5 — livrables"])

  classDef conf fill:#f1f5f9,stroke:#94a3b8,color:#334155;
  classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;
  classDef stop fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d;
  classDef data fill:#f0fdf4,stroke:#22c55e,color:#166534;

  class PYAML,PROM conf;
  class ERR1,ERR2,ERRD err;
  class ABORT1 stop;
  class ENT,USAGE,TOOLF data;
```

## 4. Les dix-sept recherches — `contract/`

Vingt-quatre critères sont déclarés, dix-sept portent une configuration Exa et
sont donc recherchés. Les sept autres — `B05` à `B11` — n'ont aucun bloc `exa:`
et ne produisent aucun constat : leurs lignes de grille restent vierges pour la
main humaine. Les dix-sept requêtes sont indépendantes sur huit fils ; l'échec
de l'une n'atteint pas les seize autres, et l'ordre de sortie est celui des
définitions, pas celui des retours.

```mermaid
flowchart TD

  ENTREE["_rechercher_constats · tool_name + offering"]
  ENTREE --> SEARCH["exa.py · search_criteria_with_exa"]
  SEARCH --> KEYX{"EXA_API_KEY ?"}
  KEYX -->|"absente"| ABORT2["CleApiManquante · code de retour 2<br/>arrêt du lot · jamais 17 constats vides<br/>déguisés en rapport complet"]
  KEYX -->|"présente"| POOL

  subgraph SG5["collect_criteria_from_exa"]
    direction TB
    POOL["ThreadPoolExecutor · 8 fils<br/>17 futures, une par critère recherché"]
    RUN["run · enveloppe chaque critère"]
    TRI["tri final selon l'ordre des définitions"]
    POOL --> RUN
  end

  CYAML[("configs/recherche_criteres/ · 24 YAML<br/>+ configs/recherche_defaults.yaml")]
  CRIT["contract/criteres.py — à l'import :<br/>fusion profonde defaults × critère<br/>identifiants uniques · type Exa supporté<br/>placeholders connus · préfixe = partie<br/>parties A et B toutes deux présentes"]
  PART["CRITERIA = 24 · A01–A13 + B01–B11<br/>CRITERIA_SEARCHES = 17 · ceux qui déclarent un bloc exa<br/>13 en partie A, 4 en partie B"]
  CYAML --> CRIT --> PART
  PART --> POOL
  PART -.->|"B05 à B11, sans bloc exa"| NOSEARCH["aucune recherche, aucun constat<br/>ligne de grille laissée vierge"]

  subgraph SG6["_collect_one · un critère"]
    direction TB
    QUERY["render_query sur l'identité d'offre<br/>+ global_instruction"]
    KW["output_schema global · num_results<br/>contents.summary = per_page_instruction + schéma<br/>include_domains si le critère en fixe"]
    CALL["client.search"]
    PARSE["output.answer · inherent_risk F/M/E<br/>justification · costDollars"]
    SORT["source_policy.py · source_sort_key<br/>official avant other, puis score Exa, puis URL"]
    CITB["par page : summary.citation → validated_citation"]
    RETENU["dédoublonnage par URL<br/>plafond max_citations_per_criterion"]
    OUT["outcome = ok si answer non vide,<br/>sinon no_answer"]
    QUERY --> KW --> CALL --> PARSE --> SORT --> CITB --> RETENU --> OUT
  end

  RUN --> QUERY
  EXAAPI(["API Exa · exa_py"])
  CALL --> EXAAPI --> PARSE

  CALL -->|"exception réseau ou API"| SFAIL["run rattrape<br/>outcome = search_failed<br/>les 16 autres poursuivent"]

  subgraph SG7["citations.py · validated_citation"]
    direction TB
    OFFS{"begin et end fournis,<br/>dans les bornes et conformes<br/>au verbatim ?"}
    RECALC["recalcul : recherche exacte,<br/>puis motif tolérant aux espaces"]
    ANCR{"verbatim présent dans<br/>le texte de sa propre page ?"}
    DEEP["lien profond vers le passage exact<br/>fragment de texte ciblé, 12 mots<br/>ou 5 premiers + 5 derniers"]
    OFFS -->|"non"| ANCR
    ANCR -->|"oui"| RECALC --> DEEP
  end

  CITB --> OFFS
  OFFS -->|"oui"| DEEP
  ANCR -->|"non"| REJ4["citation rejetée<br/>comptée dans rejected_citations"]
  DEEP --> RETENU

  OUT --> FIND["CriterionFinding<br/>ok · no_answer · search_failed"]
  SFAIL --> TRI
  FIND --> TRI
  TRI --> SORTIE["17 CriterionFinding ordonnés"]

  classDef conf fill:#f1f5f9,stroke:#94a3b8,color:#334155;
  classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;
  classDef stop fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d;
  classDef ext fill:#ecfeff,stroke:#0891b2,color:#155e75;
  classDef human fill:#fefce8,stroke:#ca8a04,stroke-width:2px,color:#854d0e;
  classDef data fill:#f0fdf4,stroke:#22c55e,color:#166534;

  class CYAML conf;
  class SFAIL,REJ4 err;
  class ABORT2 stop;
  class EXAAPI ext;
  class NOSEARCH human;
  class PART,FIND,SORTIE data;
```

## 5. Livrables et traçabilité — `report/` + `tracing.py`

Trois fichiers par demande, puis la décision humaine. Le journal ne contient
aucun texte libre en clair. Les deux rendus s'appuient sur des gabarits Word
repérés par intitulé de tableau : un gabarit modifié fait échouer la demande,
il ne produit pas un document silencieusement incomplet.

```mermaid
flowchart TD

  STATE["InterviewState complet"]

  subgraph SG8["report/renderer.py + report/grille.py + cli"]
    direction TB
    DOCX["write_docx · fiche de qualification<br/>7 tableaux remplis par intitulé<br/>A01 et A04 alimentent la section données<br/>section 8 explicitement vidée"]
    GRILLE["write_grille · gabarit officiel<br/>partie A + un bloc « Usage évalué » par usage,<br/>4 au plus, puis registre des sources"]
    JSONF["cli._ecrire_constats<br/>output/json/NUMERO.json"]
  end

  STATE --> DOCX
  STATE --> GRILLE
  STATE --> JSONF
  TPLF[("documents_reference/<br/>SI_-_Fiche_de_qualification.docx")]
  TPLG[("documents_reference/<br/>SI_-_Grille_valuation_des_risques.docx")]
  TPLF --> DOCX
  TPLG --> GRILLE
  CRITD[("contract/criteres.py · CRITERIA<br/>libellés et ordre des 24 critères")]
  CRITD --> GRILLE

  GRILLE -->|"un critère absent du gabarit,<br/>ou bloc « Usage évalué » introuvable"| ERRG["RuntimeError<br/>demande en échec, le lot continue"]
  GRILLE -.->|"B05 à B11 sans constat"| VIERGE["7 lignes de risque laissées vierges"]

  DOCX --> RESUME
  GRILLE --> RESUME
  JSONF --> RESUME
  RESUME["résumé par demande<br/>n constats · ok · sans réponse · échec · coût"]
  RESUME --> TOTAL["coût Exa total du lot<br/>code de retour 1 si rejets ou échecs"]
  TOTAL --> HUMAN["section 8 et lignes B05–B11 vierges<br/>l'autorité désignée décide<br/>PolicyBot n'autorise rien"]

  TRACE["tracing.py · logs/log_HORODATAGE.jsonl<br/>trace_step : étape, durée, statut<br/>mask_text : longueur + sha256, jamais le texte<br/>llm_usage_summary : jetons, coûts OpenRouter et Exa"]
  STATE -.-> TRACE

  classDef conf fill:#f1f5f9,stroke:#94a3b8,color:#334155;
  classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;
  classDef human fill:#fefce8,stroke:#ca8a04,stroke-width:2px,color:#854d0e;
  classDef data fill:#f0fdf4,stroke:#22c55e,color:#166534;

  class TPLF,TPLG,CRITD conf;
  class ERRG err;
  class HUMAN,VIERGE human;
  class STATE data;
```

</content>
</invoke>
