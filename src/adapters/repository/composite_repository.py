from collections.abc import Sequence
from ports.repository import StockSplitWriterPort
from domain.models import StockSplitDisclosure

class CompositeStockSplitWriterAdapter(StockSplitWriterPort):
    """
    여러 개의 StockSplitWriterPort 구현체들을 그룹으로 묶어,
    단 한 번의 save_all 호출로 연쇄 영속화 처리를 수행하는 복합(Composite) 어댑터
    """
    
    def __init__(self, writers: Sequence[StockSplitWriterPort]) -> None:
        self.writers = writers

    def save_all(self, disclosures: list[StockSplitDisclosure]) -> None:
        """주입받은 하위 모든 WriterPort들에 대해 순차적으로 저장 처리를 지시합니다."""
        for writer in self.writers:
            try:
                writer.save_all(disclosures)
            except Exception as e:
                # 개별 영속화 도중 오류가 발생해도 다른 저장 메커니즘을 훼손하지 않기 위해 로그 후 계속 진행
                print(f"[CompositeWriter] [WARNING] Save failed on writer {writer.__class__.__name__}: {e}")
