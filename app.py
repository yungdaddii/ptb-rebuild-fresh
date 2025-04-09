from flask import Flask, render_template, request, make_response
from simple_salesforce import Salesforce
import os
from datetime import datetime
from collections import defaultdict
import logging

app = Flask(__name__, static_folder='static', template_folder='templates')

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
logger.info("Connected to Salesforce successfully!")

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
    weights = {
        'StageName': 0.5000,          # 50.00%
        'icp_fit__c': 0.0063,         # 0.63%
        'Engagement_Score__c': 0.0063,# 0.63%
        'Intent_Data__c': 0.0063,     # 0.63%
        'Past_Success__c': 0.0625,    # 6.25%
        'Total_Sales_Touches__c': 0.0625, # 6.25%
        'Number_of_Meetings__c': 0.0625,  # 6.25%
        'Contacts_Associated__c': 0.0625, # 6.25%
        'Budget_Defined__c': 0.0125,  # 1.25%
        'Need_Defined__c': 0.0313,    # 3.13%
        'Timeline_Defined__c': 0.0313,# 3.13%
        'Short_List_Defined__c': 0.0938, # 9.38%
        'High_Intent__c': 0.0625      # 6.25%
    }
    stage_map = {
        'Prospecting': 1, 'Qualification': 2, 'Needs Analysis': 3, 
        'Proposal': 4, 'Negotiation': 5, 'Closed Won': 6,
        'Negotiation/Review': 5, 'Id. Decision Makers': 3
    }
    short_list_map = {'Not Considered': 0, 'Likely': 0.5, 'Confirmed': 1}
    timeline_map = {'Not Defined': 0, 'Long Term': 0.5, 'Medium Term': 0.75, 'Short Term': 1}
    
    score = 0
    
    stage_value = stage_map.get(opportunity.get('StageName', 'Prospecting'), 1)
    score += (stage_value / 6) * 10 * weights['StageName']
    
    icp_fit = 1 if opportunity.get('icp_fit__c', False) else 0
    score += icp_fit * 10 * weights['icp_fit__c']
    
    engagement_str = opportunity.get('Engagement_Score__c', '0') or '0'
    try:
        engagement = float(engagement_str)
    except ValueError:
        engagement = 0
    score += (engagement / 10) * 10 * weights['Engagement_Score__c']
    
    intent = 1 if opportunity.get('Intent_Data__c', False) else 0
    score += intent * 10 * weights['Intent_Data__c']
    
    past_success = 1 if opportunity.get('Past_Success__c', False) else 0
    score += past_success * 10 * weights['Past_Success__c']
    
    touches_str = opportunity.get('Total_Sales_Touches__c', '0') or '0'
    try:
        sales_touches = min(float(touches_str), 10)
    except ValueError:
        sales_touches = 0
    score += (sales_touches / 10) * 10 * weights['Total_Sales_Touches__c']
    
    meetings_str = opportunity.get('Number_of_Meetings__c', '0') or '0'
    try:
        meetings = min(float(meetings_str), 10)
    except ValueError:
        meetings = 0
    score += (meetings / 10) * 10 * weights['Number_of_Meetings__c']
    
    contacts_str = opportunity.get('Contacts_Associated__c', '0') or '0'
    try:
        contacts = min(float(contacts_str), 10)
    except ValueError:
        contacts = 0
    score += (contacts / 10) * 10 * weights['Contacts_Associated__c']
    
    budget = 1 if opportunity.get('Budget_Defined__c', False) else 0
    score += budget * 10 * weights['Budget_Defined__c']
    
    need = 1 if opportunity.get('Need_Defined__c', False) else 0
    score += need * 10 * weights['Need_Defined__c']
    
    timeline_value = opportunity.get('Timeline_Defined__c', 'Not Defined') or 'Not Defined'
    timeline = timeline_map.get(timeline_value, 0)
    score += timeline * 10 * weights['Timeline_Defined__c']
    
    short_list_value = opportunity.get('Short_List_Defined__c', 'Not Considered') or 'Not Considered'
    short_list = short_list_map.get(short_list_value, 0)
    score += short_list * 10 * weights['Short_List_Defined__c']
    
    high_intent = 1 if opportunity.get('High_Intent__c', False) else 0
    score += high_intent * 10 * weights['High_Intent__c']
    
    propensity_score = min(round(score, 2), 10)
    win_prob = min(round(propensity_score * 10, 2), 100)
    amount = float(opportunity.get('Amount', 0) or 0)
    # Updated to match Salesforce picklist values
    priority = ('Top Priority' if win_prob >= 80 and amount >= 1500000 else 
                'High Priority' if win_prob >= 60 else 
                'Medium Priority' if win_prob >= 40 else 'Low Priority')
    
    return propensity_score, win_prob, priority, amount

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
        
        old_propensity = opp.get('Propensity_Score__c', 0) or 0
        old_win_prob = opp.get('Win_Probability__c', 0) or 0
        old_priority = opp.get('Priority_Level__c', 'Low Priority') or 'Low Priority'
        
        if (propensity_score != old_propensity or 
            win_prob != old_win_prob or 
            priority != old_priority):
            try:
                sf.Opportunity.update(opp['Id'], {
                    'Propensity_Score__c': propensity_score,
                    'Win_Probability__c': win_prob,
                    'Priority_Level__c': priority
                })
                logger.info(f"Updated SFDC for {opp['Id']}: Propensity={propensity_score}, WinProb={win_prob}, Priority={priority}")
            except Exception as e:
                logger.error(f"Failed to update SFDC for {opp['Id']}: {str(e)}")
        
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
        opp['Amount'] = amount
        logger.debug(f"Scored {opp['Id']}: Propensity={propensity_score}, WinProb={win_prob}")

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

if __name__ == '__main__':
    app.run(debug=True, port=5001)