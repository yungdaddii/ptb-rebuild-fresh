import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class OpportunityService:
    def __init__(self, salesforce_service):
        self.sf = salesforce_service

    def calculate_propensity(self, opportunity):
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

    def update_opportunity_scores(self, opp_id):
        result = self.sf.query_opportunity(opp_id)
        if result['totalSize'] > 0:
            opp = result['records'][0]
            propensity_score, win_prob, priority, amount = self.calculate_propensity(opp)
            try:
                self.sf.update_opportunity(opp_id, {
                    'Propensity_Score__c': propensity_score,
                    'Win_Probability__c': win_prob,
                    'Priority_Level__c': priority
                })
                logger.info(f"Updated SFDC for {opp_id}: Propensity={propensity_score}, WinProb={win_prob}, Priority={priority}")
            except Exception as e:
                logger.error(f"Failed to update SFDC for {opp_id}: {str(e)}") 