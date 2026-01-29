import os
import sys
import json
import shutil
import tempfile
import zipfile
import logging
from dataclasses import asdict

# Add src to path
sys.path.append(os.path.abspath("src"))

from code_analyzer.parse_code import ASTManager
from file_system_analyzer.project_structure_analyzer import analyze_project_structure
from graph_builder.output_builder import GraphOutputBuilder
from graph_builder.ast_inserter import ASTInserter
from graph_builder.graph_queries import GraphQueries

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_runner")

def run_test(project_id, zip_path):
    temp_dir = tempfile.mkdtemp(prefix=f"test-lua-{project_id}-")
    try:
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        ast_manager = ASTManager()
        ast_manager.clear()
        
        project_items = analyze_project_structure(extract_dir)
        lua_files = [item for item in project_items if item["type"] == "file"]
        
        graph_builder = GraphOutputBuilder()
        ast_inserter = ASTInserter(graph_builder)
        ast_inserter.insert_dir_struct(project_items)
        
        for file_item in lua_files:
            file_path = file_item["path"]
            ast = ast_manager.parse(file_path)
            ast_inserter.insert_node(ast.root_node, file=file_path)
        
        graph_queries = GraphQueries(graph_builder)
        graph_queries.build_KG()
        
        # Export CPG v1
        cpg_v1_data = graph_builder.export_cpg_v1(project_id)
        
        # Save to file
        output_path = f"test_cpg_v1_{project_id}.json"
        with open(output_path, "w") as f:
            json.dump(cpg_v1_data, f, indent=2)
        
        # Find the UNKNOWN edge
        for i, edge in enumerate(cpg_v1_data["edges"]):
            if edge["type"] == "UNKNOWN":
                print(f"Found UNKNOWN edge at index {i}: {edge}")
                # Find source and target nodes
                src = next((n for n in cpg_v1_data["nodes"] if n["id"] == edge["source"]), None)
                tgt = next((n for n in cpg_v1_data["nodes"] if n["id"] == edge["target"]), None)
                print(f"  Source: {src['type'] if src else '??'} ({src['properties'].get('kind') if src else '??'})")
                print(f"  Target: {tgt['type'] if tgt else '??'} ({tgt['properties'].get('kind') if tgt else '??'})")
                # We only need to see one or two
                if i > 180: break
        
        print(f"Successfully generated CPG v1: {output_path}")
        print(f"Nodes: {len(cpg_v1_data['nodes'])}")
        print(f"Edges: {len(cpg_v1_data['edges'])}")
        
        # Try to validate if jsonschema is available
        try:
            import jsonschema
            schema_path = os.path.abspath("../schema/v1/cpg.export.schema.json")
            with open(schema_path, "r") as f:
                schema = json.load(f)
            
            # The export schema references node and edge schemas via relative paths.
            # The $id in the schemas (e.g., "schema/v1/cpg.node.schema.json") requires
            # the base URI to be the root directory containing the 'schema' folder.
            schema_dir = os.path.dirname(schema_path)
            base_dir = os.path.dirname(os.path.dirname(schema_dir))
            resolver = jsonschema.RefResolver(
                base_uri=f"file://{base_dir}/",
                referrer=schema
            )
            jsonschema.validate(instance=cpg_v1_data, schema=schema, resolver=resolver)
            print("Validation: SUCCESS")
        except ImportError:
            print("Validation: SKIPPED (jsonschema not installed)")
        except Exception as e:
            print(f"Validation: FAILED - {e}")

    finally:
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    run_test("test-project", "../test_lua_project.zip")
