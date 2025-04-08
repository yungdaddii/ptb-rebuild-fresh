from flask import Flask, render_template, request
from simple_salesforce import Salesforce
import os
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='templates')

# Salesforce connection
sf = Salesforce(
    username=os.getenv('SF_USERNAME'),
    password=os.getenv('SF_PASSWORD'),
    security_token=os.getenv('SF_TOKEN'),
    instance='propensiaai-dev-ed.develop.my.salesforce.com'
)
print("Connected to Salesforce successfully!")

# Custom Jinja2 filter for average
def average_filter(values):
    if not values:  # Handle empty list
        return 0
    return sum(float(v or 0) for v in values) / len(values)

# Register the filter
app.jinja_env.filters['average'] = average_filter

# Template filters
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

# Propensity calculation
def calculate_propensity(opportunity):
    weights = {
        'StageName': 0.50
    }
    score = 0
    stage_map = {'Prospecting': 1, 'Qualification': 2, 'Needs Analysis': 3, 
                 'Proposal': 4, 'Negotiation': 5, 'Closed Won': 6}
    
    score += stage_map.get(opportunity.get('StageName', 'Prospecting'), 1) * weights['StageName'] * 10 / 6
    
    propensity_score = min(round(score, 2), 10)
    win_prob = min(round(propensity_score * 10, 2), 100)
    amount = opportunity.get('Amount', 0) or 0  # Ensure Amount is never None
    priority = ('Top' if win_prob >= 80 and amount >= 1500000 else 
                'High' if win_prob >= 60 else 
                'Medium' if win_prob >= 40 else 'Low')
    
    return propensity_score, win_prob, priority, amount

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/score_opps')
def score_opportunities():
    # Fetch all opportunities for tiles
    all_query = "SELECT Id, Name, Amount, StageName, CloseDate FROM Opportunity"
    all_result = sf.query_all(all_query)
    all_opportunities = all_result['records']
    
    # Calculate propensity scores and ensure Amount is numeric
    for opp in all_opportunities:
        propensity_score, win_prob, priority, amount = calculate_propensity(opp)
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
        opp['Amount'] = amount  # Replace Amount with processed value

    # Pagination for table
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Show 10 opportunities per page
    offset = (page - 1) * per_page
    total_opportunities = len(all_opportunities)
    total_pages = (total_opportunities + per_page - 1) // per_page

    # Slice opportunities for the current page
    paginated_opportunities = all_opportunities[offset:offset + per_page]

    return render_template(
        'score_opps.html',
        opportunities=paginated_opportunities,  # For table
        all_opportunities=all_opportunities,    # For tiles
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_opportunities=total_opportunities
    )

if __name__ == '__main__':
    app.run(debug=True, port=5001)