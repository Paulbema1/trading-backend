from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from src.core.config import DATABASE_URL

connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    connect_args['check_same_thread'] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    if not DATABASE_URL.startswith('sqlite'):
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(10) DEFAULT 'USER';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(500);
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT TRUE;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_assets VARCHAR(200) DEFAULT 'EUR/USD,GBP/USD,USD/JPY,XAU/USD';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS stop_loss DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_1 DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_2 DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_3 DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS risk_reward DOUBLE PRECISION;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS main_timeframe VARCHAR(10);
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS confirmation_timeframe VARCHAR(10);
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS score_breakdown TEXT;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_used BOOLEAN DEFAULT FALSE;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_status VARCHAR(30);
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_summary TEXT;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS data_quality VARCHAR(10) DEFAULT 'GOOD';
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_confirmed BOOLEAN;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_reason TEXT;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS reasons TEXT;
                    ALTER TABLE signals ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                """))
                conn.commit()
        except Exception as e:
            print(f'Note migration PostgreSQL : {e}')
