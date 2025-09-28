"""
Dynamic Model Generation for Graphiti Bridge

Reads enhanced schema data from data.json and dynamically generates Pydantic models
for Graphiti custom ontology episodes.
"""

import os
import json
import logging
import threading
from typing import Dict, Any, List, Optional, Type, Union
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, create_model


class DynamicModelLoader:
    """Dynamically generates Pydantic models from enhanced data.json schema data"""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        # Prefer new plugin id 'megamem-mcp' but keep backward-compatible probe for the old id.
        # If an explicit environment variable OBSIDIAN_PLUGIN_DATA_PATH is provided, use it.
        env_path = os.environ.get('OBSIDIAN_PLUGIN_DATA_PATH')
        if env_path:
            self.data_json_path = Path(env_path)
        else:
            # primary path (new id)
            primary = self.vault_path / ".obsidian" / \
                "plugins" / "megamem-mcp" / "data.json"
            # fallback path (old id) for backcompat
            fallback = self.vault_path / ".obsidian" / \
                "plugins" / "obsidian-graphiti-mcp" / "data.json"
            # pick existing one if available, prefer primary
            if primary.exists():
                self.data_json_path = primary
            else:
                self.data_json_path = fallback
        self.entity_types: Dict[str, Type] = {}
        self.edge_types: Dict[str, Type] = {}
        self.entity_type_definitions: Dict[str, Any] = {}
        self.edge_type_definitions: Dict[str, Any] = {}
        self.edge_type_map: List[Dict[str, Any]] = []
        self.loaded = False
        self.logger = logging.getLogger('graphiti_bridge.models')

    def load_models(self) -> bool:
        """
        Load schema data from data.json and generate dynamic Pydantic models

        Returns:
            True if models were loaded successfully, False otherwise
        """
        try:
            # Check if data.json exists
            if not self.data_json_path.exists():
                self.logger.error(
                    f"Data.json not found: {self.data_json_path}")
                return False

            # Load schema data from data.json
            with open(self.data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Extract schema sections
            entity_descriptions = data.get('entityDescriptions', {})
            property_descriptions = data.get('propertyDescriptions', {})
            edge_types_data = data.get('edgeTypes', {})
            edge_type_map_data = data.get('edgeTypeMap', [])

            if not entity_descriptions and not edge_types_data:
                self.logger.warning(
                    "No entity or edge type data found in data.json")
                return False

            # Generate entity type models
            self.entity_types = self._generate_entity_models(
                entity_descriptions, property_descriptions)
            self.entity_type_definitions = self._create_entity_type_definitions(
                entity_descriptions, property_descriptions)

            # Generate edge type models
            self.edge_types = self._generate_edge_models(edge_types_data)
            self.edge_type_definitions = self._create_edge_type_definitions(
                edge_types_data)

            # Process edge type mappings
            self.edge_type_map = self._process_edge_type_map(
                edge_type_map_data)

            self.logger.info(
                f"Generated {len(self.entity_types)} entity types and {len(self.edge_types)} edge types")
            self.loaded = True
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to load models from {self.data_json_path}: {e}")
            return False

    def _generate_entity_models(self, entity_descriptions: Dict[str, Any],
                                property_descriptions: Dict[str, Any]) -> Dict[str, Type]:
        """Generate Pydantic models for entity types using data.json property mappings and selections"""
        models = {}

        # Load property mappings and selections from data.json
        with open(self.data_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        property_mappings = data.get('propertyMappings', {})
        property_selections = data.get('propertySelections', {})

        # First create BaseEntity with universal properties
        base_entity_fields: Dict[str, Any] = {
            'tags': (Optional[List[str]], Field(None, description="Topic keywords, classification labels, or categorical tags used for organizing and filtering content within the knowledge base"))
        }

        BaseEntity = create_model(
            'BaseEntity',
            __base__=BaseModel,
            __doc__="Base class for all entities with universal properties",
            **base_entity_fields
        )

        # Add BaseEntity to models dictionary
        models['BaseEntity'] = BaseEntity

        for entity_name, entity_info in entity_descriptions.items():
            try:
                # Get enabled properties for this entity
                entity_selections = property_selections.get(entity_name, {})
                enabled_properties = [
                    prop for prop, enabled in entity_selections.items() if enabled]

                # If no properties are specifically enabled, use standard entity fields as fallback
                if not enabled_properties:
                    self.logger.info(
                        f"No enabled properties for entity {entity_name}, using standard fields")
                    fields = self._get_standard_entity_fields(entity_name)
                else:
                    # Generate fields based on enabled properties and their descriptions
                    fields = self._get_entity_fields_from_data(
                        entity_name, enabled_properties, property_descriptions, property_mappings)

                # Create the model inheriting from BaseEntity
                # Extract fields safely for create_model
                safe_fields = {}
                for field_name, field_def in fields.items():
                    if isinstance(field_def, tuple) and len(field_def) == 2:
                        safe_fields[field_name] = field_def
                    else:
                        # Fallback for unexpected field format
                        safe_fields[field_name] = (Optional[str], Field(
                            None, description=f"Field {field_name}"))

                model = create_model(
                    entity_name,
                    __base__=BaseEntity,
                    __doc__=entity_info.get(
                        'description', self._get_standard_entity_description(entity_name)),
                    **safe_fields
                )

                models[entity_name] = model

            except Exception as e:
                self.logger.error(
                    f"Failed to create model for entity {entity_name}: {e}")
                continue

        return models

    def _get_entity_fields_from_data(self, entity_name: str, enabled_properties: List[str],
                                     property_descriptions: Dict[str, Any],
                                     property_mappings: Dict[str, Any]) -> Dict[str, tuple]:
        """Generate entity fields based on data.json selections and mappings"""
        fields = {}

        # Get entity-specific property descriptions
        entity_property_descriptions = property_descriptions.get(
            entity_name, {})

        for property_name in enabled_properties:
            try:
                # Use the snake_case property name directly (as stored in data.json)
                # This matches Graphiti's requirement for snake_case attributes

                # Get property description
                prop_info = entity_property_descriptions.get(property_name, {})
                description = prop_info.get(
                    'description', f"Property {property_name} for {entity_name} entities")

                # Get field type
                field_type = prop_info.get('fieldType', 'str')
                python_type = self._get_python_type(field_type)

                # Use snake_case name for the field (as required by Graphiti)
                fields[property_name] = (
                    Optional[python_type], Field(None, description=description))

            except Exception as e:
                self.logger.error(
                    f"Error processing property {property_name} for {entity_name}: {e}")
                continue

        return fields

    def _get_standard_entity_fields(self, entity_name: str) -> Dict[str, tuple]:
        """Get standard field definitions for each entity type to match reference format"""

        if entity_name == "Person":
            return {
                'givenName': (Optional[str], Field(None, description="Given name or first name of the person as commonly used in introductions and personal identification")),
                'familyName': (Optional[str], Field(None, description="Family name, surname, or last name of the person used for formal identification and family lineage")),
                'c_name': (Optional[str], Field(None, description="Complete legal name including all given names, middle names, and family names as appears on official documents")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative names, nicknames, professional names, or pseudonyms by which the person is also known")),
                'identity_type': (Optional[str], Field(None, description="Classification of person's legal and social identity status (natural_person, national_identity, pseudonym)")),
                'birthDate': (Optional[datetime], Field(None, description="Date when the person was born in YYYY-MM-DD format for biographical and age calculation purposes")),
                'address': (Optional[str], Field(None, description="Physical address, city, state, or geographic location where the person currently resides or is primarily based")),
                'email': (Optional[str], Field(None, description="Primary email address used for professional or personal communication and contact purposes")),
                'worksFor': (Optional[str], Field(None, description="Organization, company, or institution where the person is currently employed or holds a primary professional role")),
                'jobTitle': (Optional[str], Field(None, description="Current professional role, position, or title that describes the person's responsibilities and level within an organization")),
                'url': (Optional[str], Field(None, description="Personal website, professional profile, or primary online presence URL that represents the person")),
                'needs': (Optional[str], Field(None, description="Specific resources, skills, connections, or support that the person requires to achieve their goals or be successful")),
                'offers': (Optional[str], Field(None, description="Skills, services, knowledge, resources, or value that the person can provide to others or contribute to projects")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs that identify the same person on other platforms, databases, or knowledge systems for entity linking"))
            }

        elif entity_name == "Organization":
            return {
                'c_name': (Optional[str], Field(None, description="Complete legal name of the organization as registered with government authorities or incorporation documents")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative names, trade names, brand names, acronyms, or abbreviations by which the organization is commonly known")),
                'org_type': (Optional[str], Field(None, description="Legal structure and registration type of the organization (Unregistered, DAO, PMA, LLC, Inc, Partnership, 501c3, Government, etc.)")),
                'foundingDate': (Optional[datetime], Field(None, description="Date when the organization was officially established, incorporated, or founded in YYYY-MM-DD format")),
                'address': (Optional[str], Field(None, description="Physical headquarters address, primary business location, or registered office address of the organization")),
                'needs': (Optional[str], Field(None, description="Resources, partnerships, talent, funding, or capabilities that the organization requires to achieve its mission and goals")),
                'offers': (Optional[str], Field(None, description="Products, services, expertise, resources, or value propositions that the organization provides to customers or stakeholders")),
                'url': (Optional[str], Field(None, description="Official website, primary web presence, or main digital platform representing the organization")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs that identify the same organization on other platforms, databases, or knowledge systems for entity linking"))
            }

        elif entity_name == "Technology":
            return {
                'c_name': (Optional[str], Field(None, description="Complete official name of the software, technology, framework, or programming language as recognized by its creators")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative names, abbreviated forms, version names, or common references used by developers and users")),
                'category': (Optional[str], Field(None, description="Primary classification of the technology type (framework, programming language, AI model, database, API, library, platform, etc.)")),
                'opensource': (Optional[bool], Field(None, description="Whether the technology is open source software with publicly available source code and an open source license")),
                'url': (Optional[str], Field(None, description="Official documentation website, main project page, or primary resource URL for the technology")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs that identify the same technology on other platforms, repositories, or knowledge systems for entity linking"))
            }

        elif entity_name == "Product":
            return {
                'c_name': (Optional[str], Field(None, description="Complete official name of the product or service as marketed and recognized by customers and the industry")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative product names, brand variations, version names, or marketing names used across different markets or time periods")),
                'offering_type': (Optional[str], Field(None, description="Primary business model and delivery method of the offering (product, service, platform, SaaS, API, subscription, etc.)")),
                'category': (Optional[str], Field(None, description="Market segment, industry classification, or functional category that best describes the product's purpose and target market")),
                'url': (Optional[str], Field(None, description="Official product page, service portal, or primary marketing website where customers can learn about or access the offering")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs that identify the same product on other platforms, marketplaces, or knowledge systems for entity linking"))
            }

        elif entity_name == "Project":
            return {
                'c_name': (Optional[str], Field(None, description="Complete official name of the project, initiative, or undertaking as recognized by stakeholders and participants")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative project names, codenames, working titles, or informal references used during different phases of development")),
                'project_type': (Optional[str], Field(None, description="Classification of the project's primary purpose and methodology (research, development, initiative, startup, campaign, collaboration, etc.)")),
                'status': (Optional[str], Field(None, description="Current phase or state of the project lifecycle (planning, active, completed, paused, cancelled, on-hold)")),
                'needs': (Optional[str], Field(None, description="Resources, expertise, partnerships, funding, or support that the project requires to achieve its objectives and deliverables")),
                'offers': (Optional[str], Field(None, description="Outcomes, deliverables, knowledge, tools, or value that the project will produce or contribute to its field or community")),
                'url': (Optional[str], Field(None, description="Official project page, repository, documentation site, or primary web presence where information about the project is maintained")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs that identify the same project on other platforms, repositories, or knowledge systems for entity linking"))
            }

        elif entity_name == "WebPage":
            return {
                'c_name': (Optional[str], Field(None, description="Complete title or headline of the web page as it appears in the browser title bar or page header")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative titles, SEO variations, shortened versions, or social media titles used for the same content")),
                'url': (str, Field(description="Complete web address or URL where the page can be accessed on the internet")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs of archived versions, mirror sites, or equivalent content locations for the same web page"))
            }

        elif entity_name == "Note":
            return {
                'note_type': (Optional[str], Field(None, description="Classification of the note's purpose and content structure (idea, analysis, reflection, meeting_notes, research, synthesis, etc.)")),
                'author': (Optional[str], Field(None, description="Person who created, wrote, or is primarily responsible for the content and insights contained in the note")),
                'created_date': (Optional[datetime], Field(None, description="Date when the note was originally created or when the ideas were first captured in YYYY-MM-DD format"))
            }

        elif entity_name == "Article":
            return {
                'c_name': (Optional[str], Field(None, description="Complete title or headline of the published article as it appears in the final publication")),
                'aliases': (Optional[List[str]], Field(None, description="Alternative titles, working titles, social media versions, or translated titles used for the same article")),
                'article_type': (Optional[str], Field(None, description="Genre or format classification of the published content (essay, blog_post, analysis, tutorial, whitepaper, research_paper, etc.)")),
                'author': (Optional[str], Field(None, description="Person or organization who wrote, created, or is credited as the primary author of the published article")),
                'published_date': (Optional[datetime], Field(None, description="Date when the article was officially published or made publicly available in YYYY-MM-DD format")),
                'url': (Optional[str], Field(None, description="Web address where the published article can be read or accessed online")),
                'sameAs': (Optional[List[str]], Field(None, description="URIs or URLs of archived versions, republished versions, or equivalent content locations for the same article"))
            }

        else:
            # Default fields for unknown entity types
            return {
                'c_name': (Optional[str], Field(None, description=f"Complete name of the {entity_name}")),
                'aliases': (Optional[List[str]], Field(None, description=f"Alternative names for the {entity_name}")),
                'sameAs': (Optional[List[str]], Field(None, description=f"URIs that identify the same {entity_name} on other platforms"))
            }

    def _get_standard_entity_description(self, entity_name: str) -> str:
        """Get standard description for each entity type"""
        descriptions = {
            "Person": "A human actor (natural person or national identity)",
            "Organization": "An organization, company, or institution",
            "Technology": "Technology, framework, programming language, or software",
            "Product": "A product, service, or offering",
            "Project": "A project, initiative, or undertaking",
            "WebPage": "Web page, article, or documentation",
            "Note": "Personal notes and ideas",
            "Article": "Published articles and content"
        }
        return descriptions.get(entity_name, f"{entity_name} entity")

    def _generate_edge_models(self, edge_types_data: Dict[str, Any]) -> Dict[str, Type]:
        """Generate Pydantic models for edge types"""
        models = {}

        for edge_name, edge_info in edge_types_data.items():
            try:
                # Build field definitions
                fields = {}

                # DON'T add source/target/type/created - Graphiti handles these!

                # Only add edge-specific custom properties
                edge_props = edge_info.get('properties', {})
                for prop_name, prop_info in edge_props.items():
                    field_type = self._get_python_type(
                        prop_info.get('fieldType', 'str'))
                    is_required = prop_info.get('required', False)
                    description = prop_info.get(
                        'description', f"Property {prop_name} for {edge_name}")

                    if is_required:
                        fields[prop_name] = (
                            field_type, Field(description=description))
                    else:
                        fields[prop_name] = (Optional[field_type], Field(
                            default=None, description=description))

                # Create the model
                model = create_model(
                    edge_name,
                    __base__=BaseModel,
                    __doc__=edge_info.get(
                        'description', f"{edge_name} edge type"),
                    **fields
                )

                models[edge_name] = model

            except Exception as e:
                self.logger.error(
                    f"Failed to create model for edge {edge_name}: {e}")
                continue

        return models

    def _create_entity_type_definitions(self, entity_descriptions: Dict[str, Any],
                                        property_descriptions: Dict[str, Any]) -> Dict[str, Any]:
        """Create entity type definitions for Graphiti Custom Entities API"""
        definitions = {}

        for entity_name, entity_info in entity_descriptions.items():
            entity_props = property_descriptions.get(entity_name, {})

            # Build property definitions
            properties = {}
            for prop_name, prop_info in entity_props.items():
                properties[prop_name] = {
                    'type': prop_info.get('fieldType', 'str'),
                    'required': prop_info.get('required', False),
                    'description': prop_info.get('description', f"Property {prop_name}")
                }

            definitions[entity_name] = {
                'description': entity_info.get('description', f"{entity_name} entity"),
                'properties': properties
            }

        return definitions

    def _create_edge_type_definitions(self, edge_types_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create edge type definitions for Graphiti Custom Entities API"""
        definitions = {}

        for edge_name, edge_info in edge_types_data.items():
            edge_props = edge_info.get('properties', {})

            # Build property definitions
            properties = {}
            for prop_name, prop_info in edge_props.items():
                properties[prop_name] = {
                    'type': prop_info.get('fieldType', 'str'),
                    'required': prop_info.get('required', False),
                    'description': prop_info.get('description', f"Property {prop_name}")
                }

            definitions[edge_name] = {
                'description': edge_info.get('description', f"{edge_name} edge type"),
                'properties': properties
            }

        return definitions

    def _process_edge_type_map(self, edge_type_map_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process edge type mappings for internal storage"""
        processed_map = []

        for mapping in edge_type_map_data:
            processed_map.append({
                'source_entity': mapping.get('sourceEntity'),
                'target_entity': mapping.get('targetEntity'),
                'allowed_edges': mapping.get('allowedEdges', [])
            })

        return processed_map

    def _convert_edge_type_map_for_graphiti(self) -> Dict[tuple, List[str]]:
        """Convert edge type map to Graphiti format: {(source, target): [edge_types]}"""
        graphiti_map = {}

        for mapping in self.edge_type_map:
            key = (mapping['source_entity'], mapping['target_entity'])
            graphiti_map[key] = mapping['allowed_edges']

        return graphiti_map

    def _get_python_type(self, field_type_str: str) -> Type:
        """Convert field type string to Python type"""
        type_mapping = {
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'datetime': datetime,
            'List[str]': List[str],
            'List[int]': List[int],
            'List[float]': List[float]
        }

        return type_mapping.get(field_type_str, str)

    def get_entity_types(self) -> Dict[str, Type]:
        """Get dictionary of loaded entity types"""
        if not self.loaded:
            self.load_models()
        return self.entity_types

    def get_edge_types(self) -> Dict[str, Type]:
        """Get dictionary of loaded edge types"""
        if not self.loaded:
            self.load_models()
        return self.edge_types

    def get_entity_type_definitions(self) -> Dict[str, Any]:
        """Get entity type definitions for Graphiti Custom Entities API"""
        if not self.loaded:
            self.load_models()
        return self.entity_type_definitions

    def get_edge_type_definitions(self) -> Dict[str, Any]:
        """Get edge type definitions for Graphiti Custom Entities API"""
        if not self.loaded:
            self.load_models()
        return self.edge_type_definitions

    def get_edge_type_map(self) -> List[Dict[str, Any]]:
        """Get edge type mappings for internal use"""
        if not self.loaded:
            self.load_models()
        return self.edge_type_map

    def get_graphiti_entity_types(self) -> Dict[str, Type]:
        """Get entity types as dict {name: class} for Graphiti"""
        if not self.loaded:
            self.load_models()
        return self.entity_types

    def get_graphiti_edge_types(self) -> Dict[str, Type]:
        """Get edge types as dict {name: class} for Graphiti"""
        if not self.loaded:
            self.load_models()
        return self.edge_types

    def get_graphiti_edge_type_map(self) -> Dict[tuple, List[str]]:
        """Get edge type map in Graphiti format: {(source, target): [edge_types]}"""
        if not self.loaded:
            self.load_models()
        return self._convert_edge_type_map_for_graphiti()

    def get_all_types(self) -> Dict[str, Type]:
        """Get all loaded types (entities and edges combined)"""
        all_types = {}
        all_types.update(self.get_entity_types())
        all_types.update(self.get_edge_types())
        return all_types

    def create_model_instance(self, type_name: str, data: Dict[str, Any]) -> Optional[Any]:
        """
        Create an instance of a loaded model with provided data

        Args:
            type_name: Name of the model type
            data: Dictionary of field values

        Returns:
            Model instance or None if creation failed
        """
        try:
            all_types = self.get_all_types()
            if type_name not in all_types:
                self.logger.error(f"Unknown model type: {type_name}")
                return None

            model_class = all_types[type_name]
            return model_class(**data)

        except Exception as e:
            self.logger.error(f"Failed to create {type_name} instance: {e}")
            return None

    # Backward compatibility methods
    def get_node_types(self) -> Dict[str, Type]:
        """Backward compatibility method"""
        return self.get_entity_types()


def load_models_from_path(models_path: str) -> Optional[DynamicModelLoader]:
    """
    Convenience function to load models from a path

    Returns:
        DynamicModelLoader instance if successful, None otherwise
    """
    # Convert models_path to vault_path
    vault_path = Path(models_path).parent.parent if "plugins" in str(
        models_path) else Path(models_path)
    loader = DynamicModelLoader(str(vault_path))
    if loader.load_models():
        return loader
    return None


# Global model loader instance (initialized when needed)
_global_loader: Optional[DynamicModelLoader] = None
_loader_lock = threading.Lock()


def ensure_loader_initialized() -> bool:
    """Ensure global loader is initialized and loaded. Returns True if successful."""
    global _global_loader

    # Quick check without lock for performance
    if _global_loader is not None and _global_loader.loaded:
        return True

    # Thread-safe initialization
    with _loader_lock:
        # Double-check pattern
        if _global_loader is not None and _global_loader.loaded:
            return True

        logging.info("Initializing global loader...")
        try:
            from graphiti_bridge.config import get_vault_path
            vault_path = get_vault_path()

            if not vault_path:
                logging.warning(
                    "No vault path available for loader initialization")
                return False

            _global_loader = DynamicModelLoader(vault_path)
            if _global_loader.load_models():
                logging.info(
                    f"Global loader initialized with entity types: {list(_global_loader.entity_types.keys())}")
                return True
            else:
                logging.warning("Failed to load models in global loader")
                return False
        except Exception as e:
            logging.error(f"Error initializing global loader: {e}")
            return False


def get_global_loader() -> Optional[DynamicModelLoader]:
    """Get the global model loader instance"""
    return _global_loader


def initialize_global_loader(vault_path: str) -> bool:
    """Initialize the global model loader with vault path"""
    global _global_loader
    _global_loader = DynamicModelLoader(vault_path)
    return _global_loader.load_models()


def get_node_types() -> Dict[str, Type]:
    """Get entity types from global loader (backward compatibility)"""
    if _global_loader:
        return _global_loader.get_entity_types()
    return {}


def get_edge_types() -> Dict[str, Type]:
    """Get edge types from global loader (backward compatibility)"""
    if _global_loader:
        return _global_loader.get_edge_types()
    return {}


def get_entity_type_definitions() -> Dict[str, Any]:
    """Get entity type definitions for Graphiti Custom Entities API"""
    if _global_loader:
        return _global_loader.get_entity_type_definitions()
    return {}


def get_edge_type_definitions() -> Dict[str, Any]:
    """Get edge type definitions for Graphiti Custom Entities API"""
    if _global_loader:
        return _global_loader.get_edge_type_definitions()
    return {}


def get_edge_type_map() -> List[Dict[str, Any]]:
    """Get edge type mappings for internal use"""
    if _global_loader:
        return _global_loader.get_edge_type_map()
    return []


# New Graphiti-format functions
def get_graphiti_entity_types() -> Dict[str, Type]:
    """Get entity types as dict {name: class} for Graphiti"""
    if ensure_loader_initialized():
        return _global_loader.get_graphiti_entity_types()  # type: ignore
    return {}


def get_graphiti_edge_types() -> Dict[str, Type]:
    """Get edge types as dict {name: class} for Graphiti"""
    if ensure_loader_initialized():
        return _global_loader.get_graphiti_edge_types()  # type: ignore
    return {}


def get_graphiti_edge_type_map() -> Dict[tuple, List[str]]:
    """Get edge type map in Graphiti format: {(source, target): [edge_types]}"""
    if ensure_loader_initialized():
        return _global_loader.get_graphiti_edge_type_map()  # type: ignore
    return {}


def get_entity_types() -> List[str]:
    """Get all available entity types from the global loader."""
    if ensure_loader_initialized():
        try:
            entity_types = list(_global_loader.entity_types.keys())  # type: ignore
            logging.info(f"Global loader entity types: {entity_types}")
            return entity_types
        except Exception as e:
            logging.error(
                f"Error getting entity types from global loader: {e}")

    logging.warning("Using default entity types")
    return ['Person', 'Organization', 'Technology', 'Product', 'Project', 'WebPage', 'Note', 'Article']


def get_entity_types_with_config(obsidian_config: Dict[str, Any]) -> Dict[str, Type]:
    """
    Get entity types from config-specific vault path for Graphiti custom ontology

    Args:
        obsidian_config: Full Obsidian configuration dictionary

    Returns:
        Dictionary of entity type name to Pydantic model class for Graphiti
    """
    global _global_loader

    if _global_loader is not None and _global_loader.loaded:
        return _global_loader.get_graphiti_entity_types()

    try:
        import os
        from pathlib import Path

        logging.info(
            f"get_entity_types called with config keys: {list(obsidian_config.keys())}")

        # Extract vault path from config or environment
        vault_path = None

        # Try to get vault path from various potential config locations
        if 'vaultPath' in obsidian_config:
            vault_path = obsidian_config['vaultPath']
            logging.info(f"Using vaultPath from config: {vault_path}")
        elif 'vault' in obsidian_config and 'path' in obsidian_config['vault']:
            vault_path = obsidian_config['vault']['path']
            logging.info(f"Using vault.path from config: {vault_path}")
        else:
            # Derive vault path from config file location
            config_path = os.environ.get('OBSIDIAN_CONFIG_PATH')
            logging.info(f"Config path from environment: {config_path}")
            if config_path:
                # Config is typically at: vault/.obsidian/plugins/<plugin-id>/data.json
                # Previously this used 'obsidian-graphiti-mcp' — support both ids and derive vault path accordingly.
                cfg_path = Path(config_path)
                # If config_path points inside a plugin directory, climb up to vault root
                # Example: vault/.obsidian/plugins/megamem-mcp/data.json -> vault root is 3 parents up
                if 'plugins' in str(cfg_path):
                    vault_path = str(cfg_path.parent.parent.parent)
                else:
                    vault_path = str(cfg_path)
                logging.info(f"Derived vault path: {vault_path}")
            else:
                # Fallback: use the global loader if available
                if _global_loader:
                    logging.info("Using global loader as fallback")
                    return _global_loader.get_graphiti_entity_types()
                else:
                    logging.warning(
                        "No vault path found in config and no global loader available")
                    return {}

        logging.info(
            f"Attempting to load models from vault path: {vault_path}")

        # Create a temporary loader for this config
        temp_loader = DynamicModelLoader(vault_path)
        if temp_loader.load_models():
            # Initialize global loader for caching if not already set
            if _global_loader is None:
                _global_loader = temp_loader
                logging.info("Initialized global loader for caching")

            entity_types = temp_loader.get_graphiti_entity_types()
            logging.info(
                f"Successfully loaded {len(entity_types)} entity types: {list(entity_types.keys())}")
            return entity_types
        else:
            logging.warning(
                f"Failed to load models from vault path: {vault_path}")
            logging.info(
                f"Loader checked data.json at: {temp_loader.data_json_path}")
            logging.info(
                f"data.json exists: {temp_loader.data_json_path.exists()}")
            return {}

    except Exception as e:
        logging.error(f"Error getting entity types from config: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return {}
