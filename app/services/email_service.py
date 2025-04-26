from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        self.from_email = os.getenv('SENDGRID_FROM_EMAIL')

    def send_email(self, to_email, subject, content):
        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=to_email,
                subject=subject,
                html_content=content
            )
            response = self.sg.send(message)
            logger.info(f"Email sent to {to_email}. Status code: {response.status_code}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    def send_approved_emails(self, approved_emails):
        results = []
        for email in approved_emails:
            success = self.send_email(
                email['to'],
                email['subject'],
                email['content']
            )
            results.append({
                'to': email['to'],
                'success': success
            })
        return results 