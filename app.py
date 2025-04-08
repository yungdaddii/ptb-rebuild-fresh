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

# Custom filter for date formatting
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
        'StageName': 0.50,
        'Short_List_Defined__c': 0.0938,
        'Contact_Count__c': 0.0625,
        'Number_of_Meetings__c': 0.0625,
        'Sales_Touches__c': 0.0625,
        'Past_Success_Signals__c': 0.0625,
        'High_Intent__c': 0.0625,
        'Timeline_Defined__c': 0.0313,
        'Need_Defined__c': 0.0313,
        'Budget_Defined__c': 0.0125,
        'ICP_Fit__c': 0.0063,
        'Engagement_Score__c': 0.0063,
        'Intent_Data__c': 0.0063
    }
    score = 0
    stage_map = {'Prospecting': 1, 'Qualification': 2, 'Needs Analysis': 3, 
                 'Proposal': 4, 'Negotiation': 5, 'Closed Won': 6}
    
    score += stage_map.get(opportunity.get('StageName', 'Prospecting'), 1) * weights['StageName'] * 10 / 6
    for key, weight in weights.items():
        if key != 'StageName':
            value = opportunity.get(key, 0)
            if isinstance(value, bool):
                score += (1 if value else 0) * weight * 10
            elif isinstance(value, (int, float)):
                score += min(value, 10) * weight
    
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
    query = "SELECT Id, Name, Amount, StageName, CloseDate, Short_List_Defined__c, Contact_Count__c, Number_of_Meetings__c, Sales_Touches__c, Past_Success_Signals__c, High_Intent__c, Timeline_Defined__c, Need_Defined__c, Budget_Defined__c, ICP_Fit__c, Engagement_Score__c, Intent_Data__c FROM Opportunity LIMIT 10"
    opportunities = sf.query(query)['records']
    
    for opp in opportunities:
        propensity_score, win_prob, priority = calculate_propensity(opp)
        opp['Propensity_Score__c'] = propensity_score
        opp['Win_Probability__c'] = win_prob
        opp['Priority_Level__c'] = priority
    
    return render_template('score_opps.html', opportunities=opportunities)

if __name__ == '__main__':
    app.run(debug=True, port=5001)