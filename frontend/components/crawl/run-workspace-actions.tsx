import { ArrowRightCircle, Brain, Download, History } from 'lucide-react';

import { Button } from '../ui/primitives';

type RunWorkspaceActionsProps = {
  showBatch: boolean;
  batchLabel: string;
  showProductIntelligence: boolean;
  productIntelligenceLabel: string;
  showDataEnrichment: boolean;
  dataEnrichmentLabel: string;
  onBatch: () => void;
  onProductIntelligence: () => void;
  onDataEnrichment: () => void;
  onDownloadCsv: () => void;
  onDownloadJson: () => void;
  onHistory: () => void;
};

export function RunWorkspaceActions({
  showBatch,
  batchLabel,
  showProductIntelligence,
  productIntelligenceLabel,
  showDataEnrichment,
  dataEnrichmentLabel,
  onBatch,
  onProductIntelligence,
  onDataEnrichment,
  onDownloadCsv,
  onDownloadJson,
  onHistory,
}: Readonly<RunWorkspaceActionsProps>) {
  return (
    <>
      {showBatch ? (
        <Button variant="action" type="button" size="sm" onClick={onBatch}>
          <ArrowRightCircle className="size-3" />
          {batchLabel}
        </Button>
      ) : null}
      {showProductIntelligence ? (
        <Button variant="neutral" type="button" size="sm" onClick={onProductIntelligence}>
          <Brain className="size-3" />
          {productIntelligenceLabel}
        </Button>
      ) : null}
      {showDataEnrichment ? (
        <Button variant="action" type="button" size="sm" onClick={onDataEnrichment}>
          <Brain className="size-3" />
          {dataEnrichmentLabel}
        </Button>
      ) : null}
      <Button variant="download" type="button" size="sm" onClick={onDownloadCsv}>
        <Download className="size-3" />
        Excel (CSV)
      </Button>
      <Button variant="download" type="button" size="sm" onClick={onDownloadJson}>
        <Download className="size-3" />
        JSON
      </Button>
      <Button variant="neutral" type="button" size="sm" onClick={onHistory}>
        <History className="size-3" />
        History
      </Button>
    </>
  );
}
