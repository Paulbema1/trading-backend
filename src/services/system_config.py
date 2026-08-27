from sqlalchemy.orm import Session
from src.models.system_config import SystemConfig
from src.core.config import MAIN_TIMEFRAME, CONFIRMATION_TIMEFRAME

class SystemConfigService:
    def get(self, db: Session) -> SystemConfig:
        cfg = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
        if cfg is None:
            cfg = SystemConfig(id=1, main_timeframe=MAIN_TIMEFRAME, confirmation_timeframe=CONFIRMATION_TIMEFRAME)
            db.add(cfg); db.commit(); db.refresh(cfg)
        return cfg

    def update(self, db: Session, main_tf: str, confirm_tf: str) -> SystemConfig:
        cfg = self.get(db)
        cfg.main_timeframe = main_tf
        cfg.confirmation_timeframe = confirm_tf
        db.commit(); db.refresh(cfg)
        return cfg

system_config_service = SystemConfigService()
