# ptb-rebuild-fresh/app.py
from flask import Flask, render_template
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

# Custom filters
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

# Propensity calculation (simplified for standard fields)
def calculate_propensity(opportunity):
    weights = {
        'StageName': 0.50  # Only using StageName for now
    }
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
    
    return propensity_score, win_prob, priority

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/score_opps')
def score_opportunities():
    # Use only standard fields that exist
    query = "SELECT Id, Name, Amount, StageName, CloseDate FROM Opportunity LIMIT 10"
    opportunities = sf.query(query)['records']
    
    for opp in opportunities:
        propensity_score, win_prob, priority = calculate_propensity(opp)
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
    
    return render_template('score_opps.html', opportunities=opportunities)

if __name__ == '__main__':
    app.run(debug=True, port=5001)