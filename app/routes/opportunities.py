from flask import Blueprint, render_template, jsonify, request
from ..services.salesforce import SalesforceService
from ..services.opportunity_service import OpportunityService
from ..services.ai_service import AIService
from ..models.opportunity import Opportunity
from .. import db
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('opportunities', __name__)

# Initialize services
sf_service = SalesforceService()
opp_service = OpportunityService(sf_service)
ai_service = AIService()

@bp.route('/', methods=['GET'])
def get_opportunities():
    opportunities = Opportunity.query.all()
    return jsonify([{
        'id': opp.id,
        'title': opp.title,
        'description': opp.description,
        'location': opp.location,
        'start_date': opp.start_date.isoformat() if opp.start_date else None,
        'end_date': opp.end_date.isoformat() if opp.end_date else None,
        'created_at': opp.created_at.isoformat()
    } for opp in opportunities])

@bp.route('/<int:id>', methods=['GET'])
def get_opportunity(id):
    opportunity = Opportunity.query.get_or_404(id)
    return jsonify({
        'id': opportunity.id,
        'title': opportunity.title,
        'description': opportunity.description,
        'location': opportunity.location,
        'start_date': opportunity.start_date.isoformat() if opportunity.start_date else None,
        'end_date': opportunity.end_date.isoformat() if opportunity.end_date else None,
        'created_at': opportunity.created_at.isoformat()
    })

@bp.route('/', methods=['POST'])
def create_opportunity():
    data = request.get_json()
    opportunity = Opportunity(
        title=data['title'],
        description=data['description'],
        location=data['location'],
        start_date=data.get('start_date'),
        end_date=data.get('end_date')
    )
    db.session.add(opportunity)
    db.session.commit()
    return jsonify({
        'id': opportunity.id,
        'title': opportunity.title,
        'description': opportunity.description,
        'location': opportunity.location,
        'start_date': opportunity.start_date.isoformat() if opportunity.start_date else None,
        'end_date': opportunity.end_date.isoformat() if opportunity.end_date else None,
        'created_at': opportunity.created_at.isoformat()
    }), 201

@bp.route('/<int:id>', methods=['PUT'])
def update_opportunity(id):
    opportunity = Opportunity.query.get_or_404(id)
    data = request.get_json()
    
    opportunity.title = data.get('title', opportunity.title)
    opportunity.description = data.get('description', opportunity.description)
    opportunity.location = data.get('location', opportunity.location)
    opportunity.start_date = data.get('start_date', opportunity.start_date)
    opportunity.end_date = data.get('end_date', opportunity.end_date)
    
    db.session.commit()
    return jsonify({
        'id': opportunity.id,
        'title': opportunity.title,
        'description': opportunity.description,
        'location': opportunity.location,
        'start_date': opportunity.start_date.isoformat() if opportunity.start_date else None,
        'end_date': opportunity.end_date.isoformat() if opportunity.end_date else None,
        'created_at': opportunity.created_at.isoformat()
    })

@bp.route('/<int:id>', methods=['DELETE'])
def delete_opportunity(id):
    opportunity = Opportunity.query.get_or_404(id)
    db.session.delete(opportunity)
    db.session.commit()
    return '', 204

@bp.route('/<opp_id>')
def opportunity_insights(opp_id):
    try:
        # Query opportunity details
        result = sf_service.query_opportunity(opp_id)
        if result['totalSize'] == 0:
            return render_template('error.html', error="Opportunity not found")
        
        opportunity = result['records'][0]
        
        # Calculate propensity scores
        propensity_score, win_prob, priority, amount = opp_service.calculate_propensity(opportunity)
        
        # Generate next steps using AI
        next_steps = ai_service.generate_next_steps(opportunity)
        
        return render_template('opportunity_insights.html',
                             opportunity=opportunity,
                             propensity_score=propensity_score,
                             win_prob=win_prob,
                             priority=priority,
                             next_steps=next_steps)
    except Exception as e:
        logger.error(f"Error in opportunity_insights: {str(e)}")
        return render_template('error.html', error=str(e))

@bp.route('/run_initiative/<int:init_id>', methods=['GET'])
def run_initiative(init_id):
    try:
        if init_id == 1:  # Follow-up emails
            result = sf_service.query_inactive_opportunities()
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
                        email_content = ai_service.generate_follow_up_email(
                            contact_name, opp_name, account_name, amount
                        )
                        if email_content:
                            email_drafts.append({
                                'to': contact_email,
                                'subject': f"Follow-up: {opp_name} - {account_name}",
                                'content': email_content,
                                'opp_id': opp_id,
                                'contact_name': contact_name
                            })
            
            return jsonify({
                'status': 'success',
                'message': f'Generated {len(email_drafts)} email drafts',
                'emails': email_drafts
            })
            
        return jsonify({
            'status': 'error',
            'message': 'Invalid initiative ID'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in run_initiative: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@bp.route('/approve_emails/<int:init_id>', methods=['POST'])
def approve_emails(init_id):
    try:
        if init_id == 1:  # Follow-up emails
            approved_emails = request.json.get('emails', [])
            if not approved_emails:
                return jsonify({
                    'status': 'error',
                    'message': 'No emails provided'
                }), 400
            
            from ..services.email_service import EmailService
            email_service = EmailService()
            results = email_service.send_approved_emails(approved_emails)
            
            return jsonify({
                'status': 'success',
                'message': f'Sent {len(results)} emails',
                'results': results
            })
            
        return jsonify({
            'status': 'error',
            'message': 'Invalid initiative ID'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in approve_emails: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500 