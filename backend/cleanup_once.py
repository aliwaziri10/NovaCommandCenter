from app.database import SessionLocal
from app.models import Revenue, Sponsor, Video, Short, Task


def cleanup():
    db = SessionLocal()
    try:
        deleted = {}
        deleted["revenue"] = db.query(Revenue).delete()
        deleted["sponsors"] = db.query(Sponsor).delete()
        deleted["videos"] = db.query(Video).delete()
        deleted["shorts"] = db.query(Short).delete()
        deleted["tasks"] = db.query(Task).delete()
        db.commit()
        print("Cleanup complete:", deleted)
        return deleted
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    cleanup()
