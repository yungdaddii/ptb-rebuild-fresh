from flask import Blueprint, render_template
from ..services.salesforce import SalesforceService
from ..services.opportunity_service import OpportunityService
from ..services.ai_service import AIService
from ..services.email_service import EmailService
import threading
import time
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)

# Initialize services
sf_service = SalesforceService()
opp_service = OpportunityService(sf_service)
ai_service = AIService()
email_service = EmailService()

def poll_opportunity_changes():
    """Background thread to poll for opportunity changes"""
    while True:
        try:
            # Query for opportunities that need scoring
            query = "SELECT Id FROM Opportunity WHERE LastModifiedDate = TODAY"
            result = sf_service.sf.query(query)
            
            for opp in result['records']:
                opp_service.update_opportunity_scores(opp['Id'])
                
            time.sleep(300)  # Sleep for 5 minutes
        except Exception as e:
            logger.error(f"Error in opportunity polling: {str(e)}")
            time.sleep(60)  # Sleep for 1 minute on error

# Start the polling thread
polling_thread = threading.Thread(target=poll_opportunity_changes, daemon=True)
polling_thread.start()

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/score_opps')
def score_opportunities():
    try:
        # Query all opportunities
        query = """
            SELECT Id, Name, Amount, StageName, Propensity_Score__c, Win_Probability__c,
                   Priority_Level__c, LastModifiedDate
            FROM Opportunity
            ORDER BY LastModifiedDate DESC
        """
        result = sf_service.sf.query(query)
        opportunities = result['records']
        
        # Calculate metrics
        total_opps = len(opportunities)
        total_pipeline = sum(float(opp.get('Amount', 0) or 0) for opp in opportunities)
        avg_propensity = sum(float(opp.get('Propensity_Score__c', 0) or 0) for opp in opportunities) / total_opps
        avg_win_prob = sum(float(opp.get('Win_Probability__c', 0) or 0) for opp in opportunities) / total_opps
        top_priority = sum(1 for opp in opportunities if opp.get('Priority_Level__c') == 'Top Priority')
        
        return render_template('score_opps.html',
                             opportunities=opportunities,
                             total_opps=total_opps,
                             total_pipeline=total_pipeline,
                             avg_propensity=avg_propensity,
                             avg_win_prob=avg_win_prob,
                             top_priority=top_priority)
    except Exception as e:
        logger.error(f"Error in score_opportunities: {str(e)}")
        return render_template('error.html', error=str(e))

@bp.route('/ai_agents')
def ai_agents():
    return render_template('ai_agents.html') 