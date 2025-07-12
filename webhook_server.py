"""
Webhook server for handling Stripe payments and health checks
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import stripe
from dotenv import load_dotenv

from main import DatabaseManager, SubscriptionTier

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="YouTube Summarizer Webhook Server")

# Initialize services
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
db_manager = DatabaseManager()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        result = db_manager.supabase.table('users').select('count').limit(1).execute()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "database": "up",
                "stripe": "up" if stripe.api_key else "down"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Stripe webhook events"""
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        if not sig_header:
            raise HTTPException(status_code=400, detail="Missing signature")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Handle the event
        background_tasks.add_task(handle_stripe_event, event)
        
        return JSONResponse(content={"status": "success"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

async def handle_stripe_event(event):
    """Handle different Stripe events"""
    try:
        if event['type'] == 'checkout.session.completed':
            await handle_successful_payment(event['data']['object'])
        
        elif event['type'] == 'invoice.payment_succeeded':
            await handle_subscription_renewal(event['data']['object'])
        
        elif event['type'] == 'customer.subscription.deleted':
            await handle_subscription_cancelled(event['data']['object'])
        
        else:
            logger.info(f"Unhandled event type: {event['type']}")
            
    except Exception as e:
        logger.error(f"Error handling event {event['type']}: {e}")

async def handle_successful_payment(session):
    """Handle successful payment from checkout session"""
    try:
        user_id = int(session['metadata']['user_id'])
        subscription_tier = SubscriptionTier(session['metadata']['subscription_tier'])
        billing_period = session['metadata']['billing_period']
        
        # Get user from database
        user = await db_manager.get_user(user_id)
        if not user:
            logger.error(f"User {user_id} not found for payment")
            return
        
        # Update user subscription
        user.subscription_tier = subscription_tier
        user.last_payment = datetime.now()
        
        # Calculate subscription expiry
        if billing_period == 'monthly':
            user.subscription_expires = datetime.now() + timedelta(days=30)
        elif billing_period == 'yearly':
            user.subscription_expires = datetime.now() + timedelta(days=365)
        
        # Reset daily usage
        user.daily_usage = 0
        
        # Save to database
        await db_manager.update_user(user)
        
        # Save payment record
        payment_record = {
            'id': session['id'],
            'user_id': user_id,
            'amount': session['amount_total'] / 100,  # Convert from cents
            'currency': session['currency'],
            'subscription_tier': subscription_tier.value,
            'stripe_session_id': session['id'],
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        }
        
        db_manager.supabase.table('payment_records').insert(payment_record).execute()
        
        logger.info(f"Payment processed successfully for user {user_id}: {subscription_tier.value} ({billing_period})")
        
    except Exception as e:
        logger.error(f"Error handling successful payment: {e}")

async def handle_subscription_renewal(invoice):
    """Handle subscription renewal"""
    try:
        customer_id = invoice['customer']
        
        # Get customer from Stripe to find user_id
        customer = stripe.Customer.retrieve(customer_id)
        user_id = int(customer.metadata.get('user_id', 0))
        
        if not user_id:
            logger.error(f"No user_id found for customer {customer_id}")
            return
        
        # Get user and extend subscription
        user = await db_manager.get_user(user_id)
        if user:
            # Extend subscription by 30 days
            user.subscription_expires = max(
                user.subscription_expires,
                datetime.now()
            ) + timedelta(days=30)
            
            # Reset daily usage
            user.daily_usage = 0
            
            await db_manager.update_user(user)
            
            logger.info(f"Subscription renewed for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling subscription renewal: {e}")

async def handle_subscription_cancelled(subscription):
    """Handle subscription cancellation"""
    try:
        customer_id = subscription['customer']
        
        # Get customer from Stripe to find user_id
        customer = stripe.Customer.retrieve(customer_id)
        user_id = int(customer.metadata.get('user_id', 0))
        
        if not user_id:
            logger.error(f"No user_id found for customer {customer_id}")
            return
        
        # Downgrade user to free tier
        user = await db_manager.get_user(user_id)
        if user:
            user.subscription_tier = SubscriptionTier.FREE
            user.subscription_expires = datetime.now() + timedelta(days=7)  # Grace period
            
            await db_manager.update_user(user)
            
            logger.info(f"Subscription cancelled for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling subscription cancellation: {e}")

@app.get("/analytics")
async def get_analytics():
    """Get basic analytics (protected endpoint in production)"""
    try:
        # Total users
        users_result = db_manager.supabase.table('users').select('subscription_tier').execute()
        
        # Count users by subscription tier
        tier_counts = {'free': 0, 'premium': 0, 'enterprise': 0}
        for user in users_result.data:
            tier = user.get('subscription_tier', 'free')
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        
        # Total summaries
        summaries_result = db_manager.supabase.table('video_summaries').select('id').execute()
        total_summaries = len(summaries_result.data) if summaries_result.data else 0
        
        # Recent activity (last 7 days)
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        recent_result = db_manager.supabase.table('video_summaries').select('id').gte('created_at', seven_days_ago).execute()
        recent_summaries = len(recent_result.data) if recent_result.data else 0
        
        # Payment data
        payments_result = db_manager.supabase.table('payment_records').select('amount').execute()
        total_revenue = sum(float(payment.get('amount', 0)) for payment in payments_result.data) if payments_result.data else 0
        
        return {
            "users": {
                "total": sum(tier_counts.values()),
                "by_tier": tier_counts
            },
            "summaries": {
                "total": total_summaries,
                "last_7_days": recent_summaries
            },
            "revenue": {
                "total": total_revenue,
                "currency": "USD"
            },
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail="Analytics unavailable")

@app.get("/stats/usage")
async def get_usage_stats():
    """Get detailed usage statistics"""
    try:
        # Daily usage for last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        daily_usage = {}
        for i in range(30):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
            
            result = db_manager.supabase.table('video_summaries').select('id').gte('created_at', start_of_day).lte('created_at', end_of_day).execute()
            daily_usage[date_str] = len(result.data) if result.data else 0
        
        return {
            "daily_usage": daily_usage,
            "period": "30_days",
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting usage stats: {e}")
        raise HTTPException(status_code=500, detail="Usage stats unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=int(os.getenv('WEBHOOK_PORT', 8000)),
        reload=True
    )