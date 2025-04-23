from flask import Flask, render_template, request, make_response, jsonify, session
from simple_salesforce import Salesforce
from flask_session import Session
import os
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import threading
import time
from salesforce_bulk import SalesforceBulk
from langchain_openai import OpenAI
from langchain.prompts import PromptTemplate
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import json
import uuid

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', str(uuid.uuid4()))
Session(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Salesforce connection
sf = Salesforce(
    username=os.getenv('SF_USERNAME'),
    password=os.getenv('SF_PASSWORD'),
    security_token=os.getenv('SF_TOKEN'),
    instance='propensiaai-dev-ed.develop.my.salesforce.com'
)
logger.info("Connected to Salesforce REST API successfully!")

# Salesforce Bulk API
bulk = SalesforceBulk(
    username=os.getenv('SF_USERNAME'),
    password=os.getenv('SF_PASSWORD'),
    security_token=os.getenv('SF_TOKEN'),
    host='propensiaai-dev-ed.develop.my.salesforce.com'
)

# Initialize LLM
llm = None
if os.getenv('OPENAI_API_KEY'):
    try:
        llm = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        logger.info("OpenAI initialized successfully!")
    except Exception as e:
        logger.warning(f"Failed to initialize OpenAI: {str(e)}")
        logger.warning("Email generation features will be disabled")

# Custom Jinja2 filters
def average_filter(values):
    if not values:
        return 0
    return sum(float(v or 0) for v in values) / len(values)

def format_large_number(value):
    if value is None:
        return "0"
    value = float(value)
    if value >= 1000000:
        return f"{(value / 1000000):.1f}M"
    elif value >= 1000:
        return f"{(value / 1000):.1f}K"
    else:
        return "{:,}".format(int(value))

app.jinja_env.filters['average'] = average_filter
app.jinja_env.filters['format_large_number'] = format_large_number

@app.template_filter('datetimeformat')
def datetimeformat(value):
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            return value
    return "N/A"

@app.template_filter('format_number')
def format_number(value):
    return "{:,}".format(value)

def calculate_propensity(opportunity):
    """Calculate propensity score and win probability for an opportunity."""
    try:
        # Helper function to safely convert to float
        def safe_float(value, default=0.0):
            try:
                if isinstance(value, str):
                    # Remove any commas and whitespace
                    value = value.replace(',', '').strip()
                return float(value) if value else default
            except (ValueError, TypeError):
                return default

        stage_name = opportunity.get('StageName', 'Prospecting')
        amount = safe_float(opportunity.get('Amount', 0.0))
        
        if stage_name == 'Closed Won':
            return 10.0, 100.0, 'Won Deal', amount
        elif stage_name == 'Closed Lost':
            return 0.0, 0.0, 'Lost Deal', amount
        
        weights = {
            'StageName': 0.5000,
            'icp_fit__c': 0.0063,
            'Engagement_Score__c': 0.0063,
            'Intent_Data__c': 0.0063,
            'Past_Success__c': 0.0625,
            'Total_Sales_Touches__c': 0.0625,
            'Number_of_Meetings__c': 0.0625,
            'Contacts_Associated__c': 0.0625,
            'Budget_Defined__c': 0.0125,
            'Need_Defined__c': 0.0313,
            'Timeline_Defined__c': 0.0313,
            'Short_List_Defined__c': 0.0938,
            'High_Intent__c': 0.0625
        }
        stage_map = {
            'Prospecting': 1, 'Qualification': 2, 'Needs Analysis': 3,
            'Proposal': 4, 'Negotiation': 5, 'Negotiation/Review': 5,
            'Id. Decision Makers': 3
        }
        short_list_map = {'Not Considered': 0, 'Likely': 0.5, 'Confirmed': 1}
        timeline_map = {'Not Defined': 0, 'Long Term': 0.5, 'Medium Term': 0.75, 'Short Term': 1}
        
        score = 0
        stage_value = stage_map.get(stage_name, 1)
        score += (stage_value / 5) * 10 * weights['StageName']
        
        icp_fit = 1 if str(opportunity.get('icp_fit__c', 'false')).lower() == 'true' else 0
        score += icp_fit * 10 * weights['icp_fit__c']
        
        engagement_score = safe_float(opportunity.get('Engagement_Score__c', 0.0))
        score += (engagement_score / 10) * 10 * weights['Engagement_Score__c']
        
        intent = 1 if str(opportunity.get('Intent_Data__c', 'false')).lower() == 'true' else 0
        score += intent * 10 * weights['Intent_Data__c']
        
        past_success = 1 if str(opportunity.get('Past_Success__c', 'false')).lower() == 'true' else 0
        score += past_success * 10 * weights['Past_Success__c']
        
        total_sales_touches = safe_float(opportunity.get('Total_Sales_Touches__c', 0.0))
        score += (min(total_sales_touches, 10) / 10) * 10 * weights['Total_Sales_Touches__c']
        
        number_of_meetings = safe_float(opportunity.get('Number_of_Meetings__c', 0.0))
        score += (min(number_of_meetings, 10) / 10) * 10 * weights['Number_of_Meetings__c']
        
        contacts_associated = safe_float(opportunity.get('Contacts_Associated__c', 0.0))
        score += (min(contacts_associated, 10) / 10) * 10 * weights['Contacts_Associated__c']
        
        budget_defined = 1 if str(opportunity.get('Budget_Defined__c', 'false')).lower() == 'true' else 0
        score += budget_defined * 10 * weights['Budget_Defined__c']
        
        need_defined = 1 if str(opportunity.get('Need_Defined__c', 'false')).lower() == 'true' else 0
        score += need_defined * 10 * weights['Need_Defined__c']
        
        timeline_value = opportunity.get('Timeline_Defined__c', 'Not Defined') or 'Not Defined'
        timeline = timeline_map.get(timeline_value, 0)
        score += timeline * 10 * weights['Timeline_Defined__c']
        
        short_list_value = opportunity.get('Short_List_Defined__c', 'Not Considered') or 'Not Considered'
        short_list = short_list_map.get(short_list_value, 0)
        score += short_list * 10 * weights['Short_List_Defined__c']
        
        high_intent = 1 if str(opportunity.get('High_Intent__c', 'false')).lower() == 'true' else 0
        score += high_intent * 10 * weights['High_Intent__c']
        
        propensity_score = min(round(score, 2), 10)
        win_prob = min(round(propensity_score * 10, 2), 100)
        
        if win_prob >= 55 and amount >= 500000:
            priority = 'Top Priority'
        elif win_prob >= 40 and win_prob < 55 and amount >= 250000:
            priority = 'High Priority'
        elif win_prob >= 30 and win_prob < 40 and amount >= 100000:
            priority = 'Medium Priority'
        else:
            priority = 'Low Priority'
            
        return propensity_score, win_prob, priority, amount
        
    except Exception as e:
        logger.error(f"Error calculating propensity: {str(e)}")
        logger.error(f"Opportunity data: {opportunity}")
        return 0.0, 0.0, 'Error', 0.0

def update_opportunity_scores(opp_id):
    query = f"""SELECT Id, Name, Amount, StageName, icp_fit__c, Engagement_Score__c, Intent_Data__c,
                Past_Success__c, Total_Sales_Touches__c, Number_of_Meetings__c, Contacts_Associated__c,
                Budget_Defined__c, Need_Defined__c, Timeline_Defined__c, Short_List_Defined__c,
                High_Intent__c FROM Opportunity WHERE Id = '{opp_id}'"""
    result = sf.query(query)
    if result['totalSize'] > 0:
        opp = result['records'][0]
        propensity_score, win_prob, priority, amount = calculate_propensity(opp)
        try:
            sf.Opportunity.update(opp_id, {
                'Propensity_Score__c': propensity_score,
                'Win_Probability__c': win_prob,
                'Priority_Level__c': priority
            })
            logger.info(f"Updated SFDC for {opp_id}: Propensity={propensity_score}, WinProb={win_prob}, Priority={priority}")
        except Exception as e:
            logger.error(f"Failed to update SFDC for {opp_id}: {str(e)}")

def generate_follow_up_emails():
    """AI Agent: Generate follow-up emails for Prospecting Opportunities not contacted in 7 days"""
    if not llm:
        logger.warning("OpenAI not initialized. Skipping email generation.")
        return []
    
    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
    query = f"""
        SELECT Id, Name, Amount, Account.Name, LastActivityDate,
        (SELECT Contact.Name, Contact.Email FROM OpportunityContactRoles)
        FROM Opportunity
        WHERE StageName = 'Prospecting' AND (LastActivityDate <= {seven_days_ago} OR LastActivityDate IS NULL)
    """
    result = sf.query(query)
    opportunities = result['records']
    
    email_drafts = []
    
    for opp in opportunities:
        opp_id = opp['Id']
        opp_name = opp['Name']
        amount = opp.get('Amount', 0)
        account_name = opp['Account']['Name']
        
        contacts = opp.get('OpportunityContactRoles', {}).get('records', [])
        for contact in contacts:
            contact_name = contact['Contact']['Name']
            contact_email = contact['Contact']['Email']
            if contact_email:
                prompt = PromptTemplate(
                    input_variables=["contact_name", "opp_name", "account_name", "amount"],
                    template="""
                    Write a concise, professional follow-up email to {contact_name} from a sales rep at Propensia AI.
                    Reference {account_name}'s Opportunity ({opp_name}) for ${amount:,.2f}.
                    Emphasize how Propensia AI's predictive analytics can solve their sales challenges.
                    Request a meeting within 24-72 hours. Use a friendly tone and clear call-to-action.
                    """
                )
                email_content = llm.invoke(prompt.format(
                    contact_name=contact_name,
                    opp_name=opp_name,
                    account_name=account_name,
                    amount=amount
                ))
                
                email_drafts.append({
                    'OpportunityId': opp_id,
                    'ContactName': contact_name,
                    'ContactEmail': contact_email,
                    'AccountName': account_name,
                    'OpportunityName': opp_name,
                    'Amount': amount,
                    'EmailDraft': email_content
                })
    
    if email_drafts:
        with open('email_drafts.json', 'w') as f:
            json.dump(email_drafts, f, indent=2)
        session['email_drafts'] = email_drafts
        logger.info(f"Generated {len(email_drafts)} email drafts")
    else:
        logger.info("No Opportunities meet follow-up criteria")
    
    return email_drafts

def send_approved_emails(approved_emails):
    """AI Agent: Send approved emails to Contacts"""
    sendgrid_client = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
    
    for email in approved_emails:
        opp_id = email['OpportunityId']
        contact_email = email['ContactEmail']
        email_content = email['EmailDraft']
        
        message = Mail(
            from_email='sales@propensia.ai',
            to_emails=contact_email,
            subject=f"Follow-Up: {email['AccountName']} Opportunity",
            plain_text_content=email_content
        )
        
        try:
            response = sendgrid_client.send(message)
            logger.info(f"Sent email to {contact_email} for Opportunity {opp_id}: Status {response.status_code}")
            sf.Opportunity.update(opp_id, {
                'Last_Email_Sent__c': datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f"Failed to send email to {contact_email}: {str(e)}")
    
    logger.info(f"Completed sending {len(approved_emails)} emails")
    session.pop('email_drafts', None)

def poll_opportunity_changes():
    while True:
        five_minutes_ago = (datetime.utcnow() - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        query = f"""SELECT Id FROM Opportunity WHERE LastModifiedDate >= {five_minutes_ago}"""
        try:
            result = sf.query(query)
            for opp in result['records']:
                opp_id = opp['Id']
                logger.info(f"Detected modification for Opportunity {opp_id}")
                update_opportunity_scores(opp_id)
        except Exception as e:
            logger.error(f"Polling error: {str(e)}")
        time.sleep(300)

# Start polling thread
polling_thread = threading.Thread(target=poll_opportunity_changes, daemon=True)
polling_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/score_opps')
def score_opportunities():
    all_query = """SELECT Id, Name, Amount, StageName, CloseDate, LastModifiedDate,
                   icp_fit__c, Engagement_Score__c, Intent_Data__c, Past_Success__c,
                   Total_Sales_Touches__c, Number_of_Meetings__c, Contacts_Associated__c,
                   Budget_Defined__c, Need_Defined__c, Timeline_Defined__c,
                   Short_List_Defined__c, High_Intent__c,
                   Propensity_Score__c, Win_Probability__c, Priority_Level__c
                   FROM Opportunity"""
    all_result = sf.query_all(all_query)
    all_opportunities = all_result['records']
    
    logger.info(f"Fetched {len(all_opportunities)} opportunities at {datetime.now()}")
    for opp in all_opportunities[:5]:
        logger.info(f"Opportunity {opp['Id']}: StageName={opp['StageName']}, Amount={opp['Amount']}, LastModified={opp['LastModifiedDate']}")

    for opp in all_opportunities:
        propensity_score, win_prob, priority, amount = calculate_propensity(opp)
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
        opp['Amount'] = amount
        logger.debug(f"Scored {opp['Id']}: Propensity={propensity_score}, WinProb={win_prob}")

    logger.info(f"Tile - Total Opportunities: {len(all_opportunities)}")
    total_pipeline = sum(opp['Amount'] for opp in all_opportunities)
    logger.info(f"Tile - Total Open Pipeline: ${total_pipeline:,.2f}")
    avg_propensity = sum(opp['Propensity_Score__c'] for opp in all_opportunities) / len(all_opportunities)
    logger.info(f"Tile - Avg Propensity Score: {avg_propensity:.2f}")
    avg_win_prob = sum(opp['Win_Probability__c'] for opp in all_opportunities) / len(all_opportunities)
    logger.info(f"Tile - Avg Win Probability: {avg_win_prob:.2f}%")
    top_priority_count = len([opp for opp in all_opportunities if opp['Priority_Level__c'] == 'Top Priority'])
    logger.info(f"Tile - Top Priority Deals: {top_priority_count}")

    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    total_opportunities = len(all_opportunities)
    total_pages = (total_opportunities + per_page - 1) // per_page
    paginated_opportunities = all_opportunities[offset:offset + per_page]

    pipeline_by_stage = defaultdict(float)
    for opp in all_opportunities:
        pipeline_by_stage[opp['StageName']] += opp['Amount']
    stages = list(pipeline_by_stage.keys())
    pipeline_values = [pipeline_by_stage[stage] for stage in stages]
    
    closed_won_total = sum(opp['Amount'] for opp in all_opportunities if opp['StageName'] == 'Closed Won')
    
    current_year = datetime.now().year
    fy_start = f"{current_year}-01-01"
    fy_end = f"{current_year}-12-31"
    pipeline_by_close_date = defaultdict(float)
    for opp in all_opportunities:
        close_date = opp.get('CloseDate')
        if close_date and fy_start <= close_date <= fy_end:
            pipeline_by_close_date[close_date] += opp['Amount']
    close_dates = sorted(pipeline_by_close_date.keys())
    close_date_values = [pipeline_by_close_date[date] for date in close_dates]

    response = make_response(render_template(
        'score_opps.html',
        opportunities=paginated_opportunities,
        all_opportunities=all_opportunities,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_opportunities=total_opportunities,
        stages=stages,
        pipeline_values=pipeline_values,
        closed_won_total=closed_won_total,
        close_dates=close_dates,
        close_date_values=close_date_values
    ))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/ai_agents')
def ai_agents():
    initiatives = [
        {
            'id': 1,
            'name': 'Follow up with Stage 1 Opportunities',
            'description': 'Send follow-up emails to Contacts of Prospecting Opportunities not contacted in the last 7 days. Emails emphasize Propensia AI\'s value and request a meeting within 24-72 hours.'
        }
        # Add more initiatives here
    ]
    return render_template('ai_agents.html', initiatives=initiatives)

@app.route('/run_initiative/<int:init_id>', methods=['GET'])
def run_initiative(init_id):
    if init_id == 1:
        email_drafts = generate_follow_up_emails()
        if not email_drafts:
            return render_template('ai_agents.html', initiatives=[{'id': 1, 'name': 'Follow up with Stage 1 Opportunities', 'description': '...'}], message="No Opportunities meet the criteria.")
        return render_template('preview_emails.html', email_drafts=email_drafts, initiative_id=init_id)
    return jsonify({'status': 'error', 'message': 'Invalid initiative ID'})

@app.route('/approve_emails/<int:init_id>', methods=['POST'])
def approve_emails(init_id):
    if init_id != 1:
        return jsonify({'status': 'error', 'message': 'Invalid initiative ID'})
    
    selected_emails = request.form.getlist('selected_emails')
    email_drafts = session.get('email_drafts', [])
    approved_emails = [email for email in email_drafts if email['ContactEmail'] in selected_emails]
    
    if approved_emails:
        send_approved_emails(approved_emails)
        return jsonify({'status': 'success', 'message': f'Sent {len(approved_emails)} emails'})
    return jsonify({'status': 'error', 'message': 'No emails selected'})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
