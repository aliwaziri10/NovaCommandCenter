from datetime import date, timedelta

from app.database import SessionLocal
from app.models import User, Topic, Script, Video, Short, Sponsor, Revenue, Task


def seed():
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("Database already seeded, skipping.")
            return

        users = [
            User(email="admin@nova.io", name="Nova Admin", role="admin"),
            User(email="ops@nova.io", name="Operations Lead", role="operator"),
        ]
        db.add_all(users)

        topics = [
            Topic(title="AI Agents in 2026", category="Technology", trend_score=92.5, status="approved", notes="High search volume"),
            Topic(title="Passive Income Strategies", category="Finance", trend_score=88.0, status="approved"),
            Topic(title="Remote Work Productivity", category="Business", trend_score=76.3, status="research"),
            Topic(title="Crypto Market Outlook", category="Finance", trend_score=71.2, status="research"),
            Topic(title="Health Tech Innovations", category="Health", trend_score=65.8, status="approved"),
            Topic(title="Climate Tech Startups", category="Environment", trend_score=58.4, status="research"),
            Topic(title="No-Code Development", category="Technology", trend_score=84.1, status="approved"),
            Topic(title="Creator Economy Trends", category="Business", trend_score=90.2, status="approved"),
        ]
        db.add_all(topics)
        db.flush()

        scripts = [
            Script(title="AI Agents Deep Dive", content="Introduction to autonomous AI agents...", status="approved", topic_id=topics[0].id),
            Script(title="Passive Income Blueprint", content="Seven proven streams of passive income...", status="review", topic_id=topics[1].id),
            Script(title="Remote Work Mastery", content="Tools and habits for remote teams...", status="draft", topic_id=topics[2].id),
            Script(title="Health Tech Review", content="Wearables and AI diagnostics...", status="approved", topic_id=topics[4].id),
            Script(title="No-Code Revolution", content="Building apps without writing code...", status="approved", topic_id=topics[6].id),
            Script(title="Creator Economy 2026", content="Monetization strategies for creators...", status="review", topic_id=topics[7].id),
        ]
        db.add_all(scripts)
        db.flush()

        videos = [
            Video(title="AI Agents Explained", status="published", views=125000, topic_id=topics[0].id, script_id=scripts[0].id),
            Video(title="Passive Income Masterclass", status="editing", views=0, topic_id=topics[1].id, script_id=scripts[1].id),
            Video(title="Health Tech 2026", status="filming", views=0, topic_id=topics[4].id, script_id=scripts[3].id),
            Video(title="No-Code Apps Guide", status="published", views=89000, topic_id=topics[6].id, script_id=scripts[4].id),
        ]
        db.add_all(videos)
        db.flush()

        shorts = [
            Short(title="AI Agent Demo Clip", platform="youtube", status="published", views=45000, video_id=videos[0].id),
            Short(title="AI Agent TikTok", platform="tiktok", status="published", views=120000, video_id=videos[0].id),
            Short(title="Passive Income Tip #1", platform="instagram", status="draft", views=0, video_id=videos[1].id),
            Short(title="Health Tech Teaser", platform="youtube", status="draft", views=0, video_id=videos[2].id),
            Short(title="No-Code Quick Tip", platform="tiktok", status="published", views=67000, video_id=videos[3].id),
            Short(title="No-Code Reel", platform="instagram", status="published", views=34000, video_id=videos[3].id),
        ]
        db.add_all(shorts)

        sponsors = [
            Sponsor(name="TechFlow Inc", contact_email="partners@techflow.io", tier="gold", status="active"),
            Sponsor(name="CreatorHub", contact_email="sponsors@creatorhub.com", tier="silver", status="active"),
            Sponsor(name="StartupBoost", contact_email="hello@startupboost.co", tier="bronze", status="active"),
        ]
        db.add_all(sponsors)
        db.flush()

        today = date.today()
        revenue_entries = []
        for i in range(12):
            month_date = today.replace(day=1) - timedelta(days=30 * i)
            revenue_entries.extend([
                Revenue(amount=5000 + i * 200, type="sponsor", date=month_date, sponsor_id=sponsors[0].id),
                Revenue(amount=2500 + i * 100, type="sponsor", date=month_date.replace(day=min(15, month_date.day)), sponsor_id=sponsors[1].id),
                Revenue(amount=800 + i * 50, type="ad", date=month_date.replace(day=min(20, month_date.day))),
                Revenue(amount=400 + i * 30, type="affiliate", date=month_date.replace(day=min(25, month_date.day)), sponsor_id=sponsors[2].id),
            ])
        db.add_all(revenue_entries)

        tasks = [
            Task(title="Research trending AI topics", agent_name="ResearchAgent", status="completed", priority=3, payload={"source": "google_trends"}),
            Task(title="Generate script outline", agent_name="ContentAgent", status="running", priority=2, payload={"topic": "AI Agents"}),
            Task(title="Edit video thumbnails", agent_name="DesignAgent", status="pending", priority=1),
            Task(title="Analyze competitor channels", agent_name="ResearchAgent", status="pending", priority=2),
            Task(title="Schedule social posts", agent_name="SocialAgent", status="completed", priority=1),
            Task(title="Draft sponsor pitch email", agent_name="SalesAgent", status="pending", priority=3),
            Task(title="Transcribe latest video", agent_name="ContentAgent", status="failed", priority=2, payload={"video_id": "latest"}),
            Task(title="Update revenue forecast", agent_name="AnalyticsAgent", status="completed", priority=2),
            Task(title="Monitor comment sentiment", agent_name="SocialAgent", status="running", priority=1),
            Task(title="Generate KPI report", agent_name="AnalyticsAgent", status="pending", priority=3),
        ]
        db.add_all(tasks)

        db.commit()
        print("Database seeded successfully.")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed()
