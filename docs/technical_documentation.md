# Technická dokumentácia — Lua Code Analyzer

Lua Code Analyzer je mikroservis na statickú analýzu zdrojového kódu v jazyku Lua. Z každého projektu buduje **Code Property Graph (CPG)** — zlúčený model AST, znalostného grafu a medzimodulových hrán. Výsledok je publikovaný do Dapr pub/sub fronty pre ďalšie spracovanie v systéme SoftVis.

---

## Obsah

1. [Architektúra](#1-architektúra)
2. [Inštalácia](#2-inštalácia)
3. [Spustenie](#3-spustenie)
4. [Opis tried a modulov](#4-opis-tried-a-modulov)
5. [Dátový tok](#5-dátový-tok)
6. [Posielanie súborov a získavanie výstupu](#6-posielanie-súborov-a-získavanie-výstupu)
7. [Dátové typy a schéma](#7-dátové-typy-a-schéma)
8. [Konfigurácia](#8-konfigurácia)
9. [Nasadenie (Docker / Kubernetes)](#9-nasadenie-docker--kubernetes)
10. [Testy](#10-testy)

---

## 1. Architektúra

```
  RabbitMQ / Dapr                Graph Store Adapter
  (parser-code-tasks)            (ZIP so zdrojovými súbormi)
         │                                │
         ▼                                ▼
 ┌───────────────────────────────────────────────────┐
 │               dapr_handler.py (FastAPI)           │
 │    LuaCodeAnalyzerService.process_project()       │
 └──────────────────────┬────────────────────────────┘
                        │ zoznam .lua súborov
          ┌─────────────▼─────────────┐
          │     RayOrchestrator        │  ← rozposiela prácu cez Ray
          └─────────────┬─────────────┘
           Ray workers  │  (1 task = 1 súbor)
          ┌─────────────▼─────────────┐
          │     analyze_file()         │  @ray.remote(num_cpus=1)
          │  ParallelASTManager        │  → tree-sitter parse
          │  SymbolTable               │  → scope tracking
          │  GraphManager              │  → ASTInserter + SymbolBuilder + CPGBuilder
          └─────────────┬─────────────┘
                        │ lokálny výsledok (dict)
          ┌─────────────▼─────────────┐
          │     GraphCollector         │  ← sekvenčné zlučovanie
          │  _collect_local_results    │  → indexy výsledkov
          │  _create_spine             │  → adresárová štruktúra
          │  _create_indexes           │  → module/chunk/export indexy
          │  _resolve_cross_file_edges │  → require() väzby
          │  _compute_graph_metrics    │  → metriky projektu
          │  _validate_schema          │  → JSON schema check
          └─────────────┬─────────────┘
                        │ CPG v1 (JSON)
                        ▼
               graph-updates (Dapr)
```

Systém má jasnú dvojfázovú štruktúru:

| Fáza | Komponent | Paralelizmus |
|------|-----------|-------------|
| **Analýza** | Ray workers (`analyze_file`) | plne paralelná, 1 worker/súbor |
| **Zbieranie** | `GraphCollector.collect()` | sekvenčná, po dokončení všetkých workerov |

---

## 2. Inštalácia

### Požiadavky

- Python 3.11+
- `pip`
- (voliteľné) Docker, Kubernetes cluster s Dapr

### Lokálna inštalácia

```bash
# Klonovanie repozitára
git clone <repo-url>
cd GraphCreator

# Vytvorenie virtuálneho prostredia
python -m venv venv
source venv/bin/activate          # Linux / macOS
# alebo
.\venv\Scripts\activate            # Windows

# Inštalácia závislostí
pip install -r requirements.txt
```

### Závislosti (requirements.txt — kľúčové)

| Balíček | Účel |
|---------|------|
| `tree-sitter >= 0.24` | Rýchly inkrementálny parser pre Lua |
| `tree-sitter-lua >= 0.2` | Gramatika Lua pre tree-sitter |
| `ray >= 2.53` | Distribuovaný výpočet — paralelná analýza súborov |
| `fastapi` + `uvicorn` | HTTP server pre Dapr sidecar |
| `httpx` + `aiofiles` | Async HTTP klient pre sťahovanie ZIP |
| `pydantic` | Validácia vstupných správ |
| `jsonschema` | Validácia uzlov grafu oproti CPG schéme |
| `zstandard` | Kompresia veľkých grafov pred publikovaním |
| `psutil` | Meranie pamäte (RSS) |

---

## 3. Spustenie

### 3.1 Lokálne (bez Dapr)

```bash
cd src
python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080 --reload
```

Servis beží na `http://localhost:8080`. Dostupné endpointy:

| Endpoint | Metóda | Popis |
|----------|--------|-------|
| `/health` | GET | Liveness probe |
| `/ready` | GET | Readiness probe |
| `/analyze` | POST | Synchronná analýza (len na testovanie) |
| `/dapr/subscribe` | GET | Dapr konfigurácia odberov |
| `/parser-code-tasks` | POST | Prijatie Dapr CloudEvent správy |

Príklad synchronnej analýzy (debug endpoint):

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"project_id": "my-project"}'
```

### 3.2 S Dapr sidecarem

```bash
dapr run \
  --app-id lua-code-analyzer \
  --app-port 8080 \
  --dapr-http-port 3500 \
  -- python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080
```

### 3.3 Premenné prostredia

| Premenná | Predvolená hodnota | Popis |
|----------|-------------------|-------|
| `APP_PORT` | `8080` | Port HTTP servera |
| `DAPR_HTTP_PORT` | `3500` | Port Dapr sidecar HTTP API |
| `PUBSUB_NAME` | `rabbitmq-pubsub` | Názov Dapr pub/sub komponentu |
| `GRAPH_STORE_ADAPTER_APP_ID` | `graph-store-adapter` | App ID adaptéra úložiska |
| `RAY_ADDRESS` | _(auto)_ | Adresa Ray clustera; ak nie je nastavená, Ray štartuje lokálne |
| `PYTHONPATH` | `/app/src` | Musí zahŕňať `src/` adresár |

### 3.4 Spustenie testov

```bash
# Všetky testy
pytest

# S pokrytím
pytest --cov=src --cov-report=html

# Len rýchle unit testy (bez Docker)
SKIP_INTEGRATION_TESTS=true pytest

# Konkrétny modul
pytest tests/test_ray.py -v
```

---

## 4. Opis tried a modulov

### 4.1 `parser.py` — Parsovanie zdrojového kódu

#### `ASTManager`

Singleton, ktorý spravuje jeden tree-sitter parser pre celý proces. Vhodný pre sekvenčné spracovanie.

```
ASTManager (singleton)
├── parse(file_path, incremental=False) → Tree
│     Načíta .lua súbor, spustí tree-sitter parser.
│     incremental=True využíva existujúci strom na rýchlejšie re-parsovanie.
└── get_ast(file_path) → Tree
      Vráti uložený AST pre daný súbor.
```

#### `ParallelASTManager`

Inštančná (nie singleton) verzia parsera — každý Ray worker dostane vlastnú inštanciu, aby sa vyhlo race conditions pri zdieľanom stave.

```
ParallelASTManager(worker_id)
├── parse(file_path) → Tree
│     Rovnaká logika ako ASTManager.parse(), ale na izolovanej inštancii.
└── clear()
      Uvoľní všetky cachované stromy.
```

**Prečo dve triedy?** `ASTManager` je singleton — bezpečný v jednovláknovom procese. V Ray workeroch každý task beží v samostatnom Python procese, takže singleton by bol izolovaný, no pri budúcej zmene by mohol spôsobiť problémy. `ParallelASTManager` explicitne deklaruje zámer: „toto je stavová inštancia pre jedného workera".

---

### 4.2 `structures/local_symbol_table.py` — Tabuľka symbolov

#### `SymbolID`

Nemenný (`frozen=True`) dátový objekt reprezentujúci jeden symbol (premennú, funkciu, modul).

```
SymbolID
├── worker_id: str       — identifikátor workera (pre debugovanie)
├── file_path: str       — súbor, kde bol symbol definovaný
├── scope_id: str        — ID scope-u, v ktorom symbol žije
├── name: str            — meno symbolu (napr. "myFunc")
├── kind: Literal[...]   — typ: "function" | "local_variable" | "module" | ...
├── ast_id: str          — ID AST uzla, ku ktorému symbol patrí
├── start_byte: int      — pozícia začiatku v zdrojovom kóde
└── end_byte: int        — pozícia konca v zdrojovom kóde
```

#### `Scope`

Jeden lexikálny rozsah (napr. telo funkcie). Tvorí strom cez `parent`.

```
Scope
├── scope_id: str
├── parent: Optional[str]   — scope_id rodičovského scope-u
└── symbols: Dict[str, SymbolID]
```

#### `SymbolTable`

Hlavná štruktúra pre sledovanie symbolov počas analýzy jedného súboru. Každý Ray worker pracuje so svojou vlastnou inštanciou.

```
SymbolTable(worker_id)
├── scopes: Dict[str, Scope]        — všetky scope-y tohto súboru
├── exports: Dict[str, SymbolID]    — symboly exportované z modulu
├── imports: Dict[str, str]         — var_name → module_path (napr. "m" → "math.utils")
├── unresolved: Dict[str, Unresolved]
│
├── add_scope(scope) / add_export(sym) / add_import(var, module)
├── scope_lookup_by_name(scope_id, name) → Optional[SymbolID]
│     Prehľadáva scope reťazec smerom nahor (bottom-up) — implementuje Lua lexical scoping.
├── scope_lookup_by_kind(scope_id, kind) → List[SymbolID]
└── scope_lookup_by_astId(scope_id, ast_id) → Optional[SymbolID]
```

#### `ScopeStack`

Pomocná štruktúra pre `CPGBuilder` — drží zásobník aktívnych scope-ov počas prechádzania AST.

```
ScopeStack(worker_id, file_path, lst: SymbolTable)
├── push_scope(scope_id) → Scope    — vstup do nového scope (napr. začiatok funkcie)
├── pop_scope() → Scope             — výstup zo scope
├── view_scope() → str              — ID aktuálneho scope-u
└── add_to_scope(name, id, kind, s_byte, e_byte)
      Pridá symbol do aktuálneho scope a zároveň do SymbolTable.exports.
```

---

### 4.3 `builders/local_output_builder.py` — Lokálny in-memory builder

`LocalOutputBuilder` nahradil pôvodnú priamu komunikáciu s ArangoDB. Akumuluje uzly a hrany v pamäti počas analýzy jedného súboru.

#### `LocalOutputBuilder`

```
LocalOutputBuilder()
├── _nodes: Dict[str, dict]             — AST uzly (kľúč = _key)
├── _edges: List[dict]                  — AST hrany
├── knowledge_nodes: Dict[str, dict]    — uzly znalostného grafu
├── knowledge_edges: List[dict]         — hrany znalostného grafu
│
├── get_collection(name) → CollectionProxy | EdgeCollectionProxy
│     Vracia proxy objekt so ZDB-kompatibilným rozhraním (insert/get/all).
│     Podporované kolekcie: "nodes", "edges", "knowledge_nodes", "knowledge_edges"
├── export_ast_graph() → {"vertices": [...], "edges": [...]}
├── export_knowledge_graph() → {"vertices": [...], "edges": [...]}
└── clear()
```

#### `CollectionProxy` / `EdgeCollectionProxy`

Thin wrappery okolo `dict` / `list`, ktoré implementujú ArangoDB-like rozhranie (`insert`, `get`, `all`). Umožňujú použitie rovnakého kódu pre in-memory aj prípadne databázový backend.

---

### 4.4 `builders/ast_inserter.py` — Vkladanie AST do grafu

#### `ASTInserter`

Prechádza tree-sitter `Tree` a vkladá každý uzol ako vertex do `LocalOutputBuilder`. Každý uzol dostane unikátny kľúč tvaru `{file_stem}:{node_type}:{counter}`.

```
ASTInserter(graph_builder: LocalOutputBuilder)
├── insert_node(node, parent_id, file)
│     Rekurzívne prechádza AST a pre každý uzol vytvorí:
│     • vertex: {_key, ast_id, type, start_byte, end_byte, text}
│     • hranu "child_of" k rodičovskému uzlu
└── insert_dir_struct(dir_struct)
      Vloží adresárovú štruktúru projektu ako uzly.
```

---

### 4.5 `builders/cpg/` — Budovanie CPG

CPGBuilder je rozdelený do troch súborov pomocou mixin vzoru, aby sa zamedzilo vzniku jednej veľkej triedy:

| Súbor | Trieda | Zodpovednosť |
|-------|--------|-------------|
| `_cpg_base.py` | `CPGBase` | ID generátor, scope stack, vytváranie uzlov/hrán |
| `_cpg_declarations.py` | `CPGDeclarationsMixin(CPGBase)` | Spracovanie deklarácií (funkcie, premenné, chunk) |
| `_cpg_relations.py` | `CPGRelationsMixin(CPGBase)` | Vzťahové hrany (calls, assignments, control flow) |
| `lua_cpg_builder.py` | `CPGBuilder(CPGDeclarationsMixin)` | Hlavný vstupný bod, orchestruje prechádzanie AST |

#### `CPGBase`

Základná trieda s nízkoúrovňovými operáciami:

```
CPGBase(local_builder, lst: SymbolTable, file_path)
├── _create_knowledge_node(node, file_path, ...) → dict
│     Validuje typ uzla oproti množine _VALID_NODE_TYPES.
│     Generuje kľúč: "{file_name}:{type}:{counter}"
├── _create_knowledge_edge(from_id, to_id, edge_type: Edges) → dict
├── _create_unresolved_edge(node_id, symbol_name, edge_type, ...)
│     Zaregistruje hranu, ktorá sa nedá vyriešiť v rámci jedného súboru
│     (napr. referencie na iný modul). Vyriešená neskôr v GraphCollector.
├── _push_scope(s_id) / _pop_scope()
├── _handle_metrics(ast_node, k_node, *functions)
│     Vytvorí metric uzol a napojí ho cez HAS_METRICS hranu.
└── unresolved_edges: Dict[str, list]
      Akumulátor nevyriešených hrán odovzdávaný GraphCollectoru.
```

Platné typy CPG uzlov (`_VALID_NODE_TYPES`):
`chunk`, `local_function_definition`, `global_function_definition`, `local_variable_declaration`, `global_variable_declaration`, `module_import`, `module`, `identifier`, `index_expression`, `function_call`, `if_statement`, `for_statement`, `while_statement`, `repeat_statement`, `block`, `return_statement`, `table_constructor`, `literal`, `directory`, `file`, `metric`

#### `CPGBuilder`

```
CPGBuilder(local_builder, lst, file_path)
└── build(node, file_path)
      Rekurzívne prechádza AST:
      1. Ak uzol mení scope (funkcia, blok) → push_scope / pop_scope
      2. Ak je to deklarácia → create_knowledge_node_if_possible() [mixin]
      3. Ak je to vzťah → create_relation_if_possible() [mixin]
      4. Inak → rekurzívne spracuj deti
```

---

### 4.6 `managers/graph_manager.py` — Pipeline jedného súboru

`GraphManager` orchestruje celú pipeline pre jeden `.lua` súbor. Je instanciovaný pre každý Ray worker.

```
GraphManager(lst: SymbolTable)
├── generate_graph(ast: Tree, file_path: str)
│     Spustí pipeline v poradí:
│     1. ASTInserter.insert_node()     → budovanie AST grafu
│     2. SymbolBuilder.build()          → plnenie SymbolTable
│     3. CPGBuilder.build()             → budovanie CPG
│     Meria čas každej fázy do self.timings.
│
├── get_graphs() → dict
│     Vracia výsledok ako slovník:
│     {
│       "file": str,
│       "ast_graph": {"vertices": [...], "edges": [...]},
│       "knowledge_graph": {"vertices": [...], "edges": [...]},
│       "unresolved_edges": {symbol_name: [{node_id, edge_type, ...}]},
│       "exports": Dict[str, SymbolID],
│       "imports": Dict[str, str]
│     }
│
└── clear()
      Resetuje stav — uvoľní LocalOutputBuilder a SymbolTable.
```

`timings` slovník po `generate_graph()`:
- `ast_insert_s` — čas vkladania AST uzlov
- `symbol_s` — čas budovania tabuľky symbolov
- `cpg_build_s` — čas budovania CPG

---

### 4.7 `managers/cgp_worker.py` — Ray task

#### `_analyze_single(file_path)` (lokálna funkcia)

Jadro analýzy jedného súboru. Nie je Ray-specific — môže byť volaná aj priamo.

```python
worker_id = str(uuid.uuid4())       # unikátny ID pre logovanie
ast_manager = ParallelASTManager(worker_id)
lst = SymbolTable(worker_id)
gm = GraphManager(lst)

ast = ast_manager.parse(file_path)  # → Tree
gm.generate_graph(ast, file_path)   # → naplní LocalOutputBuilder
result = gm.get_graphs()            # → dict
result["_timing"] = {"parse_s": ..., **gm.timings}
return result
```

#### `analyze_file` (Ray remote function)

```python
@ray.remote(num_cpus=1)
def analyze_file(file_path: str) -> Optional[Dict]:
    return _analyze_single(file_path)
```

`@ray.remote(num_cpus=1)` rezervuje práve 1 CPU slot na task — priamo kontroluje maximálny paralelizmus (Ray cluster s `num_cpus=4` spustí najviac 4 simultánne tasky).

---

### 4.8 `managers/ray_orchestrator.py` — Distribúcia práce

```
RayOrchestrator()
├── __init__()
│     Inicializuje Ray (ignoruje reinit error — bezpečné pri opakovanom volaní).
│     Nastaví PYTHONPATH v runtime_env tak, aby workery našli src/ moduly.
│     RAY_ADDRESS z env umožňuje pripojenie na existujúci cluster.
│
└── distribute_work(files: list) → List[ray.ObjectRef]
      Pre každý {"path": str} súbor odošle analyze_file.remote(path).
      Vracia zoznam futures — volajúci si sám čaká na výsledky.
```

---

### 4.9 `builders/graph_collector.py` — Zlučovanie grafov

`GraphCollector` je sekvenčná fáza, ktorá zlúči výstupy všetkých Ray workerov do jedného projektu-level grafu.

#### `GraphCollectorBase`

Základná trieda s kolekciami a pomocnými factory metódami:

```
GraphCollectorBase
├── _ast_nodes: Dict[str, dict]
├── _ast_edges: List[dict]
├── _knowledge_nodes: Dict[str, dict]
├── _knowledge_edges: List[dict]
│
├── _add_ast_node / _add_ast_nodes / _add_ast_edge / _add_ast_edges
├── _add_knowledge_node / _add_knowledge_nodes / ...
├── _create_ast_node(...) → dict
├── _create_ast_edge(parent_id, node_id, relation) → dict
├── _create_knowledge_node(node_id, *, symbol_id, type, text, ...) → dict
└── _create_knowledge_edge(from_id, to_id, edge_type: Edges) → dict
```

#### `GraphCollector(GraphCollectorBase)`

```
GraphCollector()
├── results: Dict[str, dict]           — file_path → výsledok workera
├── _module_index: Dict[str, str]      — module_name → knowledge_node_id
├── _chunk_index: Dict[str, str]       — file_path → chunk_node_id
├── _export_index: Dict[str, Dict]     — module_name → {decl_name → node_id}
└── _declaration_index: Dict[str, Dict]— file_path → {name → node_id}
```

**`collect(results, root_directory)` — hlavná metóda**

Spúšťa pipeline v pevnom poradí a meria každú fázu:

```
1. _collect_local_results(results)
   Uloží každý workerov výsledok do self.results[file_path].

2. _create_spine(root_directory)
   Prejde adresárovú štruktúru a pre každý súbor/adresár vytvorí
   uzol v AST aj knowledge grafe. Napojí ich cez CONTAINS hrany.
   Pre každý .lua súbor zavolá _store_local_graph() — vloží workerov
   lokálny graf (AST + KG) do globálnych kolekcií.

3. _create_indexes()
   Prechádza knowledge_nodes a builduje 4 indexy:
   • module_index:      module_name → node_id
   • chunk_index:       file_path → chunk_node_id
   • export_index:      module → {name → node_id}
   • declaration_index: file → {name → node_id}

4. _resolve_cross_file_edges()
   Pre každý súbor:
   • Krok 1: require() importy → pridá IMPORTS hranu medzi
     lokálnu premennú a target module uzol.
   • Krok 2: unresolved_edges od workerov → pokúsi sa vyriešiť
     symboly cez export_index a deklaračný index.

5. _resolve_module_field_accesses()
   Hľadá index_expression uzly (m.foo) a pridá ACCESSES_EXPORT
   hranu priamo na exportovaný symbol.

6. _compute_graph_metrics()
   Vypočíta projekt-level metriky (počty uzlov, funkcií, LOC).
   Pre každú funkciu doplní dependency_metrics a global_var_metrics.

7. _validate_schema()
   Náhodne vysampluje 200 knowledge uzlov a validuje ich
   oproti schema_lua/cpg.node.schema.json. Logguje porušenia.
```

**`export_cpg_v1(project_id)` → dict**

Konvertuje interný formát do CPG v1 schémy pre publikovanie. Mapuje interné typy uzlov (`local_function_definition` → `FUNCTION`) a typy hrán (`calls` → `CALLS`).

---

### 4.10 `dapr_handler.py` — HTTP server a Dapr integrácia

#### `DaprClient`

Asynchrónny HTTP klient pre komunikáciu s Dapr sidecar.

```
DaprClient(base_url="http://localhost:3500")
├── invoke_service(app_id, method, http_method, data, params) → Response
│     Volá iný microservis cez Dapr service invocation.
│
├── publish(pubsub_name, topic, data)
│     Publikuje JSON správu na topic.
│
├── publish_compressed(pubsub_name, topic, data)
│     Serializuje → zstd kompresia (level 3) → base64 encode →
│     zabalí do envelope {"encoding": "zstd+base64", "data": ...}.
│     Používa sa pre veľké CPG grafy (typicky >50 MB pred kompresiou).
│
└── download_project_zip(project_id, dest_path) → str
      Stiahne ZIP projektu z Graph Store Adapteru cez streaming.
```

#### `LuaCodeAnalyzerService`

```
LuaCodeAnalyzerService(dapr_client)
└── process_project(project_id) → ProcessingResult
      1. Stiahne ZIP zo Graph Store Adapteru.
      2. Rozbalí do temp adresára.
      3. Analyzuje štruktúru projektu (analyze_project_structure).
      4. Odošle .lua súbory cez RayOrchestrator.
      5. Vyzdvihne výsledky cez ray.get().
      6. Zlúči cez GraphCollector.collect().
      7. Exportuje do CPG v1 (gc.export_cpg_v1()).
      8. Validuje oproti JSON schéme.
      9. Publikuje komprimovaný výsledok na "graph-updates" topic.
      10. Uvoľní temp adresár.
```

#### FastAPI endpointy

| Route | Metóda | Popis |
|-------|--------|-------|
| `/dapr/subscribe` | GET | Vracia zoznam subscriptions pre Dapr runtime |
| `/parser-code-tasks` | POST | Prijíma CloudEvent správu, spúšťa `process_project()` |
| `/health` | GET | `{"status": "healthy"}` — Kubernetes liveness probe |
| `/ready` | GET | `{"status": "ready"}` — Kubernetes readiness probe |
| `/analyze` | POST | Synchronná analýza (len pre vývoj/debugovanie) |

---

### 4.11 `dto/edges.py` — Typy hrán

`Edges` enum definuje všetky povolené typy hrán v CPG:

| Kategória | Hrany |
|-----------|-------|
| Štrukturálne | `DEFINES`, `DECLARES`, `CONTAINS`, `IMPORTS` |
| Štruktúra funkcie | `HAS_BLOCK`, `HAS_PARAMETERS`, `HAS_FIELD`, `HAS_ARGUMENT`, `HAS_CONDITION` |
| Dátový tok | `REFERS_TO`, `CALLS`, `HAS_CALLEE`, `ACCESSES_MEMBER_OF`, `ACCESSES_EXPORT`, `RETURNS`, `FLOWS_TO`, `INITIALIZES`, `ASSIGNS_TO`, `EXECUTES` |
| Graf | `IS`, `CHILD_OF`, `HAS_METRICS` |

---

### 4.12 `ast_metrics/` — Per-file metriky

Vypočítané počas `CPGBuilder.build()` a uložené ako `metric` uzly s `HAS_METRICS` hranami.

| Modul | Funkcia | Čo meria |
|-------|---------|---------- |
| `cycl_complexity.py` | `calculate_cyclomatic_complexity()` | McCabova cyklomatická zložitosť (1 + počet vetvení) |
| `halstead_metrics.py` | `calculate_halstead_metrics()` | Halsteadove metriky: n1, n2, N1, N2, objem, ťažkosť |
| `loc.py` | `calculate_loc()` | Riadky kódu (celkové, kódové, komentáre) |
| `function_counts.py` | `count_functions()` | Počet lokálnych a globálnych funkcií |
| `statement_usage.py` | `count_statements()` | Počet rôznych typov príkazov |
| `info_flow.py` | `calculate_info_flow()` | Fan-in / fan-out funkcie |

---

### 4.13 `graph_metrics/` — Projekt-level metriky

Vypočítané v `GraphCollector._compute_graph_metrics()` po zlúčení všetkých súborov.

| Modul | Funkcia | Čo meria |
|-------|---------|----------|
| `project_metrics.py` | `compute_project_metrics()` | Celkový počet súborov, modulov, priemerná LOC, priemerná CC |
| `dependency_metrics.py` | `compute_dependency_metrics()` | Fan-in / fan-out na úrovni projektu pre každú funkciu |
| `global_var_metrics.py` | `compute_global_var_metrics()` | Prístupy ku globálnym premenným na funkciu |

---

## 5. Dátový tok

### Per-file výsledok (výstup `GraphManager.get_graphs()`)

```json
{
  "file": "/tmp/project/src/utils.lua",
  "ast_graph": {
    "vertices": [{"_key": "utils:chunk:1", "type": "chunk", ...}],
    "edges":    [{"_from": "utils:chunk:1", "_to": "utils:identifier:2", "relation": "child_of"}]
  },
  "knowledge_graph": {
    "vertices": [{"_key": "utils:local_function_definition:1", "type": "local_function_definition", ...}],
    "edges":    [{"_from": "utils:module:1", "_to": "utils:local_function_definition:1", "relation": "defines"}]
  },
  "unresolved_edges": {
    "my_symbol": [{"node_id": "...", "edge_type": "refers_to", "scope": "...", "file": "..."}]
  },
  "exports": {"my_func": {"name": "my_func", "kind": "local_function", ...}},
  "imports": {"m": "math.utils"}
}
```

### CPG v1 výstup (výstup `GraphCollector.export_cpg_v1()`)

```json
{
  "meta_data": {
    "schema_version": "v1",
    "languages": ["lua"],
    "analysis_date": "2026-05-09T10:00:00+00:00",
    "graph_id": "my-project",
    "project_id": "my-project"
  },
  "nodes": [
    {
      "id": "my-project:utils:local_function_definition:1",
      "type": "FUNCTION",
      "properties": {"kind": "local_function_definition", "language": "lua", "code": "function foo()"},
      "location": {"start_offset": 0, "end_offset": 42, "file": "/tmp/.../utils.lua"}
    }
  ],
  "edges": [
    {
      "source": "my-project:utils:module:1",
      "target": "my-project:utils:local_function_definition:1",
      "type": "DEFINES",
      "properties": {"relation": "defines"}
    }
  ]
}
```

---

## 6. Posielanie súborov a získavanie výstupu

Servis podporuje dva spôsoby spracovania projektov: produkčný (cez Dapr pub/sub) a vývojový (priame HTTP volanie).

---

### 6.1 Produkčný tok — Dapr pub/sub

```
Klient                  RabbitMQ / Dapr               Lua Code Analyzer
  │                          │                                │
  │── publish ──────────────►│                                │
  │   topic: parser-code-tasks                                │
  │   {"project_id": "abc"}  │                                │
  │                          │── POST /parser-code-tasks ────►│
  │                          │                                │── stiahne ZIP
  │                          │                                │── analyzuje
  │                          │◄── graph-updates ──────────────│
  │                          │    (CPG v1, komprimovaný)      │
  │                          │◄── results ────────────────────│
  │                          │    (stav spracovania)          │
```

**Krok 1 — Publikovanie úlohy:**

Pred analýzou musí byť ZIP súbor projektu nahraný do Graph Store Adapteru. Servis si ho sám stiahne podľa `project_id`.

```bash
# Publikovanie cez Dapr HTTP API (z iného mikroservisu alebo curl)
curl -X POST http://localhost:3500/v1.0/publish/rabbitmq-pubsub/parser-code-tasks \
  -H "Content-Type: application/json" \
  -d '{"project_id": "my-lua-project"}'
```

**Krok 2 — Príjem výstupu:**

Výsledok je publikovaný na dva topics:

| Topic | Obsah | Formát |
|-------|-------|--------|
| `graph-updates` | Kompletný CPG v1 graf | zstd+base64 komprimovaný JSON |
| `results` | Stav spracovania | Čistý JSON |

Odber `results` topic (Dapr subscription):
```json
{
  "project_id": "my-lua-project",
  "status": "completed",
  "files_processed": 47,
  "files_failed": 0,
  "errors": [],
  "message": "Successfully processed 47 files"
}
```

Dekomprimovanie výstupu z `graph-updates`:
```python
import base64, zstandard as zstd, json

envelope = {...}          # správa z topic graph-updates
compressed = base64.b64decode(envelope["data"])
decompressor = zstd.ZstdDecompressor()
cpg_json = json.loads(decompressor.decompress(compressed))
# cpg_json → {"meta_data": {...}, "nodes": [...], "edges": [...]}
```

---

### 6.2 Vývojový tok — synchronný HTTP endpoint

Pre testovanie bez Dapr a RabbitMQ je k dispozícii `/analyze` endpoint. Predpokladá, že ZIP súbor je dostupný cez Graph Store Adapter (alebo nakonfigurovanú cestu).

```bash
# Spustenie servisu lokálne
cd src
python -m uvicorn dapr_handler:app --host 0.0.0.0 --port 8080 --reload

# Synchronná analýza projektu
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"project_id": "my-lua-project"}'
```

Odpoveď:
```json
{
  "project_id": "my-lua-project",
  "status": "completed",
  "files_processed": 47,
  "files_failed": 0,
  "errors": [],
  "message": "Successfully processed 47 files"
}
```

> **Poznámka:** `/analyze` vracia len stav spracovania, nie samotný CPG. CPG je vždy publikovaný na Dapr topic `graph-updates`. Pre lokálne testovanie bez Dapr použite priamu Python API (pozri 6.3).

---

### 6.3 Priama Python API (bez servisu)

Pre integračné testy alebo dávkové spracovanie je možné volať pipeline priamo, bez spúšťania FastAPI servera ani Dapr:

```python
import sys
sys.path.insert(0, "src")

from benchmarks.datasets import extract_dataset
from benchmarks.runner import run_benchmark_on_dir

# Rozbalí ZIP dataset a vráti zoznam súborov
extract_dir, files = extract_dataset("kong")

# Spustí plnú pipeline (Ray + GraphCollector)
result = run_benchmark_on_dir(extract_dir, files, dataset_name="kong", num_cpus=4)

print(f"Uzlov: {result.n_knowledge_nodes}, Hrán: {result.n_knowledge_edges}")
print(f"Čas: {result.time_total_s:.2f}s")
```

Pre prístup ku grafu samotného `GraphCollector` objektu (nie len metriky):

```python
import ray
from managers.ray_orchestrator import RayOrchestrator
from builders.graph_collector import GraphCollector

ray.init(num_cpus=4, runtime_env={"env_vars": {"PYTHONPATH": "src"}})

orchestrator = RayOrchestrator()
futures = orchestrator.distribute_work(files)   # files = [{"path": "/abs/path/file.lua"}, ...]
results = [r for r in ray.get(futures) if r is not None]

gc = GraphCollector()
gc.collect(results, extract_dir)

# Prístup k zlúčenému grafu
print(f"AST uzlov:       {len(gc._ast_nodes)}")
print(f"Knowledge uzlov: {len(gc._knowledge_nodes)}")
print(f"Knowledge hrán:  {len(gc._knowledge_edges)}")

# Export do CPG v1
cpg = gc.export_cpg_v1("moj-projekt")
import json
with open("output_cpg.json", "w") as f:
    json.dump(cpg, f, indent=2)

ray.shutdown()
```

---

### 6.4 Formát vstupného zoznamu súborov

`RayOrchestrator.distribute_work()` a `run_benchmark_on_dir()` očakávajú zoznam slovníkov s kľúčom `"path"`:

```python
files = [
    {"path": "/tmp/project/src/utils.lua"},
    {"path": "/tmp/project/src/main.lua"},
    {"path": "/tmp/project/lib/math.lua"},
]
```

Absolútne cesty sú povinné — relatívne cesty worker nerozlíši, keďže Ray môže spustiť task na inom stroji s inou pracovnou cestou.

---

## 7. Dátové typy a schéma  

Schémy sú v adresári `schema/`:

| Súbor | Popis |
|-------|-------|
| `cpg.node.schema.json` | JSON Schema pre jeden CPG uzol |
| `cpg.edge.schema.json` | JSON Schema pre jednu CPG hranu |
| `cpg.export.schema.json` | JSON Schema pre celý CPG export (odkazuje na node/edge schémy) |

Lokálna validácia uzlov sa vykonáva v `GraphCollector._validate_schema()` — náhodný vzorkový test 200 uzlov z celého grafu.

---

## 8. Konfigurácia

### Ray cluster

Pre produkčné nasadenie v Kubernetes sa odporúča KubeRay. Príklad manifestu je v `manifests/raycluster.yaml`.

Servis sa pripojí na existujúci cluster cez:
```bash
export RAY_ADDRESS="ray://ray-head-svc:10001"
```

Bez nastavenia `RAY_ADDRESS` Ray štartuje lokálny cluster s dostupnými CPU jadrami.

### Dapr komponenty

`manifests/dapr-pubsub.yaml` — definuje RabbitMQ pub/sub komponent pre Dapr.

Kľúčové nastavenia:
- `spec.type: pubsub.rabbitmq`
- `metadata.name: rabbitmq-pubsub` — musí zodpovedať `PUBSUB_NAME`

### KEDA auto-scaling

`manifests/keda-scaledobject.yaml` — škáluje počet podov podľa dĺžky fronty `parser-code-tasks`.

---

## 9. Nasadenie (Docker / Kubernetes)

### Docker

Dockerfile je dvojfázový (builder → production):

1. **Builder stage** — nainštaluje build nástroje a závislosti do izolovaného `/opt/venv`
2. **Production stage** — skopíruje len venv + zdrojový kód; beží ako non-root `appuser`

Štruktúra kopírovaných súborov v kontajneri:

```
/app/
├── src/                          ← celý src/ strom (PYTHONPATH=/app/src)
│   ├── dapr_handler.py
│   ├── parser.py
│   ├── managers/
│   ├── builders/
│   ├── structures/
│   ├── ast_metrics/
│   ├── graph_metrics/
│   └── dto/
├── schema/v1/                    ← schémy pre dapr_handler.py
│   ├── cpg.node.schema.json
│   ├── cpg.edge.schema.json
│   └── cpg.export.schema.json
└── schema_lua/                   ← schémy pre graph_collector.py
    ├── cpg.node.schema.json
    └── ...
```

```bash
# Build image
docker build -t lua-code-analyzer:latest .

# Lokálne spustenie (bez Dapr)
docker run -p 8080:8080 \
  -e RAY_ADDRESS="" \
  lua-code-analyzer:latest

# S pripojením na externý Ray cluster
docker run -p 8080:8080 \
  -e RAY_ADDRESS="ray://ray-head:10001" \
  -e DAPR_HTTP_PORT=3500 \
  lua-code-analyzer:latest

# Overenie
curl http://localhost:8080/health
```

### Kubernetes — produkcia

Predpoklady: `kubectl` nainštalovaný lokálne, `~/.kube/config` nakonfigurovaný na cieľový cluster, image pushnutý do registry.

```bash
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/rabbitmq.yaml
kubectl apply -f manifests/dapr-pubsub.yaml
kubectl apply -f manifests/raycluster.yaml
kubectl apply -f manifests/deployment.yaml
kubectl apply -f manifests/service.yaml
kubectl apply -f manifests/keda-scaledobject.yaml
```

Zdravotné sondy sú nakonfigurované na `/health` (liveness) a `/ready` (readiness).

> **Dôležité:** Pred spustením `kubectl apply` je nutné vytvoriť Kubernetes Secret pre RabbitMQ (pozri sekciu nižšie). Bez neho Dapr sidecar okamžite padne.

---

### Kubernetes — lokálny vývoj s kind

`kind` (Kubernetes in Docker) je lokálny cluster bežiaci ako Docker kontajner. Jeho node používa `containerd` ako container runtime — **nie** Docker daemon. Tieto dve úložiská sú úplne oddelené:

```
Tvoj stroj
├── Docker daemon
│   └── lua-code-analyzer:latest  ← tu je image po docker build
└── kind cluster (Docker kontajner)
    └── graphcreator-control-plane (node)
        └── containerd             ← iný runtime, nevidí Docker images
```

Z tohto dôvodu `imagePullPolicy: Always` v produkcii **nefunguje** pre kind — node sa pokúsi stiahnuť image z `registry.example.com/...` (placeholder URL), zlyhá a Pod zasekne v `ErrImagePull`.

**Postup pre kind:**

```bash
# 1. Zbuilduj image
docker build -t lua-code-analyzer:latest .

# 2. Exportuj z Docker a importuj do kind node (do containerd)
#    kind load = docker save | ctr images import vo vnútri node kontajnera
kind load docker-image lua-code-analyzer:latest --name graphcreator

# 3. Aplikuj manifesty
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/rabbitmq.yaml
kubectl apply -f manifests/dapr-pubsub.yaml
kubectl apply -f manifests/raycluster.yaml
kubectl apply -f manifests/deployment.yaml
kubectl apply -f manifests/service.yaml
# keda-scaledobject.yaml vynechaj ak nemáš KEDA — pozri poznámku nižšie

# 4. Oprav deployment pre kind (produkčné hodnoty nefungujú lokálne)
kubectl set image deployment/lua-code-analyzer \
  lua-code-analyzer=lua-code-analyzer:latest -n parsers

kubectl patch deployment lua-code-analyzer -n parsers \
  --type='json' \
  -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"},
    {"op":"replace","path":"/spec/replicas","value":1}
  ]'
```

**Overenie:**

```bash
# Skontroluj či bežia oba kontajnery (app + dapr sidecar = 2/2)
kubectl get pods -n parsers

# Port-forward a otestuj health endpoint
kubectl port-forward -n parsers deployment/lua-code-analyzer 18080:8080
curl http://localhost:18080/health
# → {"status":"healthy","service":"lua-code-analyzer"}
curl http://localhost:18080/ready
# → {"status":"ready"}
```

---

### RabbitMQ Secret — povinný krok pred nasadením

`dapr-pubsub.yaml` odkazuje na Kubernetes Secret namiesto hardcoded credentials:

```yaml
metadata:
  - name: connectionString
    secretKeyRef:
      name: rabbitmq-secret       # ← tento Secret musí existovať
      key: connection-string
```

Bez tohto Secretu Dapr sidecar okamžite zlyhá s:
```
Fatal error: failed to load components: Secret "rabbitmq-secret" not found
```

Secret sa **zámerene** nenachádza v git repozitári (obsahuje citlivé údaje). Vytvor ho raz manuálne pred prvým nasadením:

```bash
# Produkcia — nahraď hodnoty skutočnými credentials
kubectl create secret generic rabbitmq-secret \
  -n parsers \
  --from-literal=connection-string="amqp://USER:PASS@rabbitmq.parsers.svc.cluster.local:5672"

# Lokálny kind cluster — credentials z manifests/rabbitmq.yaml
kubectl create secret generic rabbitmq-secret \
  -n parsers \
  --from-literal=connection-string="amqp://user:password@rabbitmq.parsers.svc.cluster.local:5672"
```

Format connection stringu: `amqp://{user}:{pass}@{hostname}:{port}`

Hostname `rabbitmq.parsers.svc.cluster.local` je Kubernetes DNS meno:
- `rabbitmq` — meno Service objektu
- `parsers` — namespace
- `svc.cluster.local` — štandardný Kubernetes DNS suffix

V produkčnom prostredí odporúčame spravovať Secrets cez **External Secrets Operator** (napojený na Vault alebo cloud secret manager) namiesto manuálneho `kubectl create secret`.

---

### KEDA a `replicas: 0`

Deployment má predvolene `replicas: 0` — žiadny Pod nevznikne kým KEDA nezačne škálovať. KEDA sleduje dĺžku fronty `parser-code-tasks` v RabbitMQ:

```
Fronta prázdna  →  KEDA: replicas=0  →  0 Podov (šetrí zdroje)
Správa príde    →  KEDA: replicas=1+ →  Pod vznikne, spracuje správu
Fronta prázdna  →  KEDA: scale-down na 0
```

Pre lokálny vývoj bez KEDA nastav `replicas` manuálne:
```bash
kubectl patch deployment lua-code-analyzer -n parsers \
  --type='json' -p='[{"op":"replace","path":"/spec/replicas","value":1}]'
```

Alebo vynechaj `manifests/keda-scaledobject.yaml` a uprav `replicas: 1` priamo v `deployment.yaml` pred aplikovaním.

---

## 10. Testy

Testy sú v adresári `tests/`.

| Súbor | Čo testuje |
|-------|-----------|
| `test_ray.py` | Integračné testy celej pipeline — od parse po GraphCollector |
| `test_symbol_table.py` | Unit testy SymbolTable, scope lookup, lexical scoping |

Spustenie:

```bash
# Všetky testy s verbose výstupom
pytest tests/ -v

# Len testy symblovej tabuľky
pytest tests/test_symbol_table.py -v

# Len Ray/integration testy
pytest tests/test_ray.py -v
```
