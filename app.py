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
    weights = {'StageName': 0.50}
    score = 0
    stage_map = {'Prospecting': 1, 'Qualification': 2, 'Needs Analysis': 3, 
                 'Proposal': 4, 'Negotiation': 5, 'Closed Won': 6}
    
    score += stage_map.get(opportunity.get('StageName', 'Prospecting'), 1) * weights['StageName'] * 10 / 6
    
    propensity_score = min(round(score, 2), 10)
    win_prob = min(round(propensity_score * 10, 2), 100)
    amount = opportunity.get('Amount', 0) or 0
    priority = ('Top' if win_prob >= 80 and amount >= 1500000 else 
                'High' if win_prob >= 60 else 
                'Medium' if win_prob >= 40 else 'Low')
    
    return propensity_score, win_prob, priority, amount

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/score_opps')
def score_opportunities():
    # Fetch fresh data with timestamp to avoid caching
    all_query = "SELECT Id, Name, Amount, StageName, CloseDate, LastModifiedDate FROM Opportunity"
    all_result = sf.query_all(all_query)
    all_opportunities = all_result['records']
    
    logger.info(f"Fetched {len(all_opportunities)} opportunities at {datetime.now()}")

    for opp in all_opportunities:
        propensity_score, win_prob, priority, amount = calculate_propensity(opp)
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
        opp['Amount'] = amount

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    total_opportunities = len(all_opportunities)
    total_pages = (total_opportunities + per_page - 1) // per_page
    paginated_opportunities = all_opportunities[offset:offset + per_page]

    # Chart data (omitted for brevity, unchanged)
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

    # Render response with no-cache headers
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