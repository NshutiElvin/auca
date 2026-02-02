from rest_framework import serializers
import json

class ConfigSerializer(serializers.Serializer):
    config = serializers.JSONField()
    
    def validate_config(self, value):
        """Validate that the value is valid JSON"""
        try:
            # Ensure it's JSON serializable
            json.dumps(value)
            return value
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError(f"Invalid JSON data: {str(e)}")