from simple_salesforce import Salesforce
from salesforce_bulk import SalesforceBulk
import os
import logging

logger = logging.getLogger(__name__)

class SalesforceService:
    def __init__(self):
        self.sf = Salesforce(
            username=os.getenv('SF_USERNAME'),
            password=os.getenv('SF_PASSWORD'),
            security_token=os.getenv('SF_TOKEN'),
            instance='propensiaai-dev-ed.develop.my.salesforce.com'
        )
        logger.info("Connected to Salesforce REST API successfully!")

        self.bulk = SalesforceBulk(
            username=os.getenv('SF_USERNAME'),
            password=os.getenv('SF_PASSWORD'),
            security_token=os.getenv('SF_TOKEN'),
            host='propensiaai-dev-ed.develop.my.salesforce.com'
        )

    def query_opportunity(self, opp_id):
        query = f"""SELECT Id, Name, Amount, StageName, icp_fit__c, Engagement_Score__c, Intent_Data__c,
                    Past_Success__c, Total_Sales_Touches__c, Number_of_Meetings__c, Contacts_Associated__c,
                    Budget_Defined__c, Need_Defined__c, Timeline_Defined__c, Short_List_Defined__c,
                    High_Intent__c FROM Opportunity WHERE Id = '{opp_id}'"""
        return self.sf.query(query)

    def update_opportunity(self, opp_id, data):
        return self.sf.Opportunity.update(opp_id, data)

    def query_inactive_opportunities(self, days=7):
        from datetime import datetime, timedelta
        date_threshold = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        query = f"""
            SELECT Id, Name, Amount, Account.Name, LastActivityDate,
            (SELECT Contact.Name, Contact.Email FROM OpportunityContactRoles)
            FROM Opportunity
            WHERE StageName = 'Prospecting' AND (LastActivityDate <= {date_threshold} OR LastActivityDate IS NULL)
        """
        return self.sf.query(query) 