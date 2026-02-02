import json
import os
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class JsonConfigManager:
    def __init__(self, config_path=None):
        self.config_path = config_path or getattr(
            settings, 'CONFIG_JSON_PATH', 'config/config.json'
        )
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
    
    def read_config(self):
        """Read JSON configuration file"""
        try:
            if not os.path.exists(self.config_path):
                # Create default config if file doesn't exist
                default_config = {"settings": {}, "version": "1.0.0"}
                self._write_config(default_config)
                return default_config
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise ValueError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            logger.error(f"Error reading config file: {e}")
            raise
    
    def write_config(self, config_data):
        """Write JSON configuration file"""
        try:
            # Validate it's valid JSON-serializable data
            json.dumps(config_data)  # Test serialization
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Config file updated: {self.config_path}")
            return True
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid data for JSON: {e}")
            raise ValueError(f"Invalid JSON data: {str(e)}")
        except Exception as e:
            logger.error(f"Error writing config file: {e}")
            raise
    
    def update_config(self, updates):
        """Update specific fields in config"""
        current_config = self.read_config()
        current_config.update(updates)
        self.write_config(current_config)
        return current_config
    
    def _write_config(self, config_data):
        """Internal method to write config (for initialization)"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)