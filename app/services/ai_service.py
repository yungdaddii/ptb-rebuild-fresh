import openai
import os
import logging

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.client = None
        if os.getenv('OPENAI_API_KEY'):
            try:
                openai.api_key = os.getenv('OPENAI_API_KEY')
                self.client = openai.OpenAI()
                logger.info("OpenAI initialized successfully!")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI: {str(e)}")
                logger.warning("Email generation features will be disabled")

    def generate_follow_up_email(self, contact_name, opp_name, account_name, amount):
        if not self.client:
            logger.warning("OpenAI not initialized. Cannot generate email.")
            return None

        prompt = f"""
        Write a concise, professional follow-up email to {contact_name} from a sales rep at Propensia AI.
        Reference {account_name}'s Opportunity ({opp_name}) for ${amount:,.2f}.
        Emphasize how Propensia AI's predictive analytics can solve their sales challenges.
        Request a meeting within 24-72 hours. Use a friendly tone and clear call-to-action.
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error generating email: {str(e)}")
            return None

    def generate_next_steps(self, opportunity):
        if not self.client:
            logger.warning("OpenAI not initialized. Cannot generate next steps.")
            return None

        prompt = f"""
        Analyze this sales opportunity and provide 3-5 specific next steps:
        {opportunity}
        
        Focus on:
        1. Immediate actions to advance the deal
        2. Key stakeholders to engage
        3. Potential risks to address
        4. Timeline considerations
        
        Format as a bulleted list with clear, actionable items.
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error generating next steps: {str(e)}")
            return None 