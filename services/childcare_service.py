from models.childcare import Child, ChildActivityType, DailyChildcareActivity, MonthlyChildcareSummary
from models.transactions import Transaction
from models.categories import Category
from models.accounts import Account
from services.payday_service import PaydayService
from extensions import db
from datetime import datetime, date, timedelta
from decimal import Decimal
from calendar import monthrange


class ChildcareService:
    
    @staticmethod
    def get_or_create_child(name, year_group=None):
        """Get existing child or create new one"""
        child = Child.query.filter_by(name=name).first()
        if not child:
            child = Child(name=name, year_group=year_group)
            db.session.add(child)
            db.session.commit()
        return child
    
    @staticmethod
    def add_activity_type(child_id, name, cost, provider=None):
        """Add an activity type for a child"""
        activity_type = ChildActivityType(
            child_id=child_id,
            name=name,
            cost=cost,
            provider=provider
        )
        db.session.add(activity_type)
        db.session.commit()
        return activity_type
    
    @staticmethod
    def get_monthly_calendar(year, month):
        """
        Get calendar data for a month with all childcare activities.
        Returns a structure suitable for rendering a calendar view.
        """
        # Get all active children
        children = Child.query.filter_by(is_active=True).order_by(Child.sort_order, Child.name).all()
        
        # Get first and last day of month
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        # Get all activities for this month (eager load relationships)
        activities = DailyChildcareActivity.query.options(
            db.joinedload(DailyChildcareActivity.activity_type)
        ).filter(
            DailyChildcareActivity.date >= first_day,
            DailyChildcareActivity.date <= last_day
        ).all()
        
        # Organize activities by date and child
        calendar_data = {}
        current_date = first_day
        while current_date <= last_day:
            day_data = {
                'date': current_date,
                'day_name': current_date.strftime('%A'),
                'children': {}
            }
            
            for child in children:
                child_activities = [a for a in activities if a.date == current_date and a.child_id == child.id]
                day_data['children'][child.id] = {
                    'child': child,
                    'activities': child_activities,
                    'total': sum([a.actual_cost for a in child_activities if a.occurred], Decimal('0'))
                }
            
            day_data['total'] = sum([child_data['total'] for child_data in day_data['children'].values()], Decimal('0'))
            calendar_data[current_date] = day_data
            current_date += timedelta(days=1)
        
        return calendar_data, children
    
    @staticmethod
    def update_daily_activity(date, child_id, activity_type_id, occurred, cost_override=None):
        """Update or create a daily activity record"""
        activity = DailyChildcareActivity.query.filter_by(
            date=date,
            child_id=child_id,
            activity_type_id=activity_type_id
        ).first()
        
        if not activity:
            activity = DailyChildcareActivity(
                date=date,
                child_id=child_id,
                activity_type_id=activity_type_id,
                occurred=occurred
            )
            db.session.add(activity)
        else:
            activity.occurred = occurred
        
        if cost_override is not None:
            activity.cost_override = cost_override
        
        db.session.commit()
        db.session.refresh(activity)  # Ensure we have the latest state
        return activity
    
    @staticmethod
    def get_monthly_totals(year, month):
        """Calculate monthly totals for each child"""
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        activities = DailyChildcareActivity.query.filter(
            DailyChildcareActivity.date >= first_day,
            DailyChildcareActivity.date <= last_day,
            DailyChildcareActivity.occurred == True
        ).all()
        
        # Group by child
        totals = {}
        for activity in activities:
            child_id = activity.child_id
            if child_id not in totals:
                totals[child_id] = {
                    'child': activity.child,
                    'total': Decimal('0'),
                    'activities': []
                }
            totals[child_id]['total'] += activity.actual_cost
            totals[child_id]['activities'].append(activity)
        
        return totals
    
    @staticmethod
    def create_monthly_transaction(year, month, child_id, account_id):
        """
        Create a transaction for the month's childcare costs for a specific child.
        Returns the created transaction.
        """
        year_month = f"{year}-{month:02d}"
        
        # Calculate total for this child this month
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        activities = DailyChildcareActivity.query.filter(
            DailyChildcareActivity.date >= first_day,
            DailyChildcareActivity.date <= last_day,
            DailyChildcareActivity.child_id == child_id,
            DailyChildcareActivity.occurred == True
        ).all()
        
        total_cost = sum([a.actual_cost for a in activities], Decimal('0'))
        
        if total_cost <= 0:
            return None
        
        # Get child
        child = Child.query.get(child_id)
        
        # Use configured category or create default Childcare category
        if child.category_id:
            category_id = child.category_id
        else:
            # Get or create Childcare category
            category = Category.query.filter_by(
                name='Childcare',
                category_type='Expense'
            ).first()
            
            if not category:
                category = Category(
                    name='Childcare',
                    category_type='Expense',
                    head_budget='Childcare',
                    sub_budget='Childcare'
                )
                db.session.add(category)
                db.session.commit()
            
            category_id = category.id
        
        # Use configured transaction day (default 28th)
        transaction_day = min(child.transaction_day or 28, monthrange(year, month)[1])
        transaction_date = date(year, month, transaction_day)
        
        # Calculate computed fields
        payday_period = PaydayService.get_period_for_date(transaction_date)
        year_month = transaction_date.strftime('%Y-%m')
        week_year = f"{transaction_date.isocalendar()[1]:02d}-{transaction_date.year}"
        day_name = transaction_date.strftime('%a')
        
        # Create transaction (negative amount = expense in new convention)
        transaction = Transaction(
            transaction_date=transaction_date,
            account_id=account_id,
            category_id=category_id,
            vendor_id=child.vendor_id,  # Use configured vendor
            amount=-total_cost,  # Negative for expense
            description=f"Childcare - {child.name} - {year_month}",
            item=f"{child.name} Childcare",
            is_paid=False,
            payment_type='Direct Debit',
            year_month=year_month,
            week_year=week_year,
            day_name=day_name,
            payday_period=payday_period
        )
        db.session.add(transaction)
        db.session.commit()
        
        # Create or update monthly summary
        summary = MonthlyChildcareSummary.query.filter_by(
            year_month=year_month,
            child_id=child_id
        ).first()
        
        if not summary:
            summary = MonthlyChildcareSummary(
                year_month=year_month,
                child_id=child_id,
                total_cost=total_cost,
                transaction_id=transaction.id,
                account_id=account_id
            )
            db.session.add(summary)
        else:
            summary.total_cost = total_cost
            summary.transaction_id = transaction.id
            summary.account_id = account_id
        
        db.session.commit()
        return transaction
    
    @staticmethod
    def get_annual_costs(year, child_id=None):
        """Get annual childcare costs for a specific year"""
        query = MonthlyChildcareSummary.query.filter(
            MonthlyChildcareSummary.year_month.like(f'{year}%')
        )
        
        if child_id:
            query = query.filter_by(child_id=child_id)
        
        summaries = query.all()
        
        total = sum([s.total_cost for s in summaries], Decimal('0'))
        
        return {
            'year': year,
            'total': total,
            'summaries': summaries,
            'by_child': ChildcareService._group_by_child(summaries)
        }
    
    @staticmethod
    def _group_by_child(summaries):
        """Group summaries by child"""
        grouped = {}
        for summary in summaries:
            child_id = summary.child_id
            if child_id not in grouped:
                grouped[child_id] = {
                    'child': summary.child,
                    'total': Decimal('0'),
                    'months': []
                }
            grouped[child_id]['total'] += summary.total_cost
            grouped[child_id]['months'].append(summary)
        return grouped
    
    @staticmethod
    def bulk_update_week(start_date, child_id, activity_configs):
        """
        Bulk update activities for a week.
        activity_configs = {
            'Monday': [activity_type_id1, activity_type_id2],
            'Tuesday': [activity_type_id1],
            ...
        }
        """
        current_date = start_date
        for i in range(7):
            day_name = current_date.strftime('%A')
            if day_name in activity_configs:
                for activity_type_id in activity_configs[day_name]:
                    ChildcareService.update_daily_activity(
                        current_date,
                        child_id,
                        activity_type_id,
                        occurred=True
                    )
            current_date += timedelta(days=1)
    
    @staticmethod
    def apply_templates_to_month(year, month):
        """
        Apply all activity type templates to entire month based on their weekly patterns.
        This populates all activities according to their defined weekly schedule.
        """
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        # Get all active children and their activity types
        children = Child.query.filter_by(is_active=True).all()
        
        current_date = first_day
        count = 0
        
        while current_date <= last_day:
            weekday = current_date.weekday()  # 0=Monday, 6=Sunday
            
            for child in children:
                for activity_type in child.activity_types:
                    if activity_type.is_active and activity_type.occurs_on_weekday(weekday):
                        ChildcareService.update_daily_activity(
                            current_date,
                            child.id,
                            activity_type.id,
                            occurred=True
                        )
                        count += 1
            
            current_date += timedelta(days=1)
        
        return count
    
    @staticmethod
    def copy_previous_month(year, month):
        """
        Copy all activities from previous month to current month.
        Matches dates by day of week and position in month.
        """
        # Calculate previous month
        if month == 1:
            prev_year = year - 1
            prev_month = 12
        else:
            prev_year = year
            prev_month = month - 1
        
        # Get previous month's activities
        prev_first_day = date(prev_year, prev_month, 1)
        prev_last_day = date(prev_year, prev_month, monthrange(prev_year, prev_month)[1])
        
        prev_activities = DailyChildcareActivity.query.filter(
            DailyChildcareActivity.date >= prev_first_day,
            DailyChildcareActivity.date <= prev_last_day,
            DailyChildcareActivity.occurred == True
        ).all()
        
        # Copy to current month
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        count = 0
        for prev_activity in prev_activities:
            # Calculate the corresponding date in current month
            day_offset = (prev_activity.date - prev_first_day).days
            new_date = first_day + timedelta(days=day_offset)
            
            # Only copy if new date is within the current month
            if new_date <= last_day:
                ChildcareService.update_daily_activity(
                    new_date,
                    prev_activity.child_id,
                    prev_activity.activity_type_id,
                    occurred=True,
                    cost_override=prev_activity.cost_override
                )
                count += 1
        
        return count
    
    @staticmethod
    def clear_month(year, month):
        """Clear all activities for a month"""
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        deleted = DailyChildcareActivity.query.filter(
            DailyChildcareActivity.date >= first_day,
            DailyChildcareActivity.date <= last_day
        ).delete()
        
        db.session.commit()
        return deleted
