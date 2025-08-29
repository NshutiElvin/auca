from django.contrib.auth.password_validation import (
    UserAttributeSimilarityValidator,
    MinimumLengthValidator,
    CommonPasswordValidator,
    NumericPasswordValidator
)
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
import re

class PasswordStrengthValidator:
    """
    Validates password strength and returns a score (0-100) with feedback.
    """
    def __init__(self, min_length=8):
        self.min_length = min_length
    
    def validate(self, password, user=None):
        """
        Validate whether the password meets the minimum requirements.
        Raises ValidationError if it doesn't.
        """
        if len(password) < self.min_length:
            raise ValidationError(
                _("This password is too short. It must contain at least %(min_length)d characters."),
                code='password_too_short',
                params={'min_length': self.min_length},
            )
    
    def get_help_text(self):
        return _(
            "Your password must contain at least %(min_length)d characters."
            % {'min_length': self.min_length}
        )
    
    def get_strength_score(self, password, user=None):
        """
        Returns a tuple (score, feedback) where score is a number between 0-100 
        and feedback is a dictionary of improvement suggestions.
        """
        score = 0
        feedback = {
            'suggestions': [],
            'warnings': []
        }
        
        # Length check (up to 40 points)
        length_score = min(40, len(password) * 4)
        score += length_score
        
        if len(password) < 8:
            feedback['warnings'].append('Your password is too short')
        
        # Character variety (up to 30 points)
        if re.search(r'[A-Z]', password):
            score += 7
        else:
            feedback['suggestions'].append('Add uppercase letters')
        
        if re.search(r'[a-z]', password):
            score += 7
        else:
            feedback['suggestions'].append('Add lowercase letters')
        
        if re.search(r'[0-9]', password):
            score += 7
        else:
            feedback['suggestions'].append('Add numbers')
        
        if re.search(r'[^a-zA-Z0-9]', password):
            score += 9
        else:
            feedback['suggestions'].append('Add special characters')
        
        # Complexity patterns (up to 30 points)
        # Check for sequences
        if not re.search(r'(.)\1{2,}', password):  # No character repeated 3+ times
            score += 10
        else:
            feedback['warnings'].append('Avoid repeating characters')
        
        # Check for patterns like 12345 or abcde
        has_sequence = False
        for i in range(len(password) - 2):
            chunk = password[i:i+3]
            if chunk.isdigit() and int(chunk[1]) - int(chunk[0]) == int(chunk[2]) - int(chunk[1]) == 1:
                has_sequence = True
                break
            if chunk.isalpha() and ord(chunk[1]) - ord(chunk[0]) == ord(chunk[2]) - ord(chunk[1]) == 1:
                has_sequence = True
                break
        
        if not has_sequence:
            score += 10
        else:
            feedback['warnings'].append('Avoid sequential characters')
        
        # Check similarity to common passwords
        try:
            CommonPasswordValidator().validate(password)
            score += 10
        except ValidationError:
            feedback['warnings'].append('This password is too common')
        
        # User attribute similarity if user is provided
        if user:
            try:
                UserAttributeSimilarityValidator().validate(password, user)
            except ValidationError:
                score -= 20
                feedback['warnings'].append('Password contains personal information')
        
        # Ensure score is within 0-100
        score = max(0, min(100, score))
        
        # Categorize strength
        strength = 'very weak'
        if score >= 80:
            strength = 'very strong'
        elif score >= 60:
            strength = 'strong'
        elif score >= 40:
            strength = 'medium'
        elif score >= 20:
            strength = 'weak'
        
        return {
            'score': score,
            'strength': strength,
            'feedback': feedback
        }


def get_password_strength(password, user=None):
    """
    Utility function to get password strength without creating an instance
    """
    validator = PasswordStrengthValidator()
    return validator.get_strength_score(password, user)