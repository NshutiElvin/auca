import resend
import os
 
resend.api_key = os.environ.get("RESEND_API_KEY")
 
 
def send_mail(subject, message, from_email, recipient_list, **kwargs):
    
    from_email = from_email or os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    resend.Emails.send({
        "from": from_email,
        "to": recipient_list,
        "subject": subject,
        "text": message,
    })
 