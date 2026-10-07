import logging
import smtplib
from email.message import EmailMessage
from typing import List

from ai_service.app.core.config import settings
from ai_service.app.schemas.match import JobWithMatch

logger = logging.getLogger("jobpilot.email")

class EmailService:
    def __init__(self, threshold: float = settings.high_match_threshold):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.from_email = settings.smtp_from_email
        self.to_email = settings.smtp_user if settings.smtp_user else "user@example.com"
        self.threshold = threshold
        
    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.to_email)

    def notify_high_matches(self, items: List[JobWithMatch], limit: int = 10) -> int:
        if not self.is_configured:
            return 0
            
        hits = [i for i in items if i.match and i.match.passed_hard_filters and i.match.overall_match >= self.threshold]
        if not hits:
            return 0
            
        hits = hits[:limit]
        
        # Build HTML content
        html_lines = [
            f"<h2>JobPilot Found {len(hits)} New High-Match Jobs</h2>",
            "<ul style='list-style-type: none; padding: 0;'>"
        ]
        
        for item in hits:
            job = item.job
            match = item.match
            html_lines.append(
                f"<li style='margin-bottom: 20px; border: 1px solid #ddd; padding: 10px; border-radius: 5px;'>"
                f"  <h3 style='margin-top: 0;'><a href='{job.application_url}'>{job.title} at {job.company}</a></h3>"
                f"  <p><strong>Match:</strong> {match.overall_match:.0f}%</p>"
                f"  <p><strong>Location:</strong> {job.location} ({job.workplace_type.value})</p>"
                f"  <p><strong>Visa:</strong> {job.visa_sponsorship.status.value}</p>"
                f"</li>"
            )
        html_lines.append("</ul>")
        
        html_body = "\n".join(html_lines)
        subject = f"JobPilot: {len(hits)} New Matches ({hits[0].job.title} and more)"
        
        success = self.send_email(self.to_email, subject, html_body)
        return len(hits) if success else 0

    def send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self.from_email
        msg['To'] = to_email
        
        msg.set_content("Please enable HTML to view this message.")
        msg.add_alternative(html_body, subtype='html')
        
        try:
            logger.info(f"Sending email to {to_email}: {subject}")
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=15)
                if self.port == 587 or self.port == 25:
                    server.starttls()
                    
            if self.user and self.password:
                server.login(self.user, self.password)
                
            server.send_message(msg)
            server.quit()
            logger.info(f"Successfully sent email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

email_service = EmailService()
