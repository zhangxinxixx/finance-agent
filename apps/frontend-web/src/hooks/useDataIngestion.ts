import { useEffect, useState } from "react";
import { fetchDataIngestionData } from "@/adapters/dataIngestion";
import type { DataIngestionResponse } from "@/types/data-ingestion";

interface DataIngestionState {
  data: DataIngestionResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useDataIngestion(): DataIngestionState {
  const [data, setData] = useState<DataIngestionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadDataIngestion() {
      setIsLoading(true);
      setError(null);

      try {
        const nextData = await fetchDataIngestionData();

        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Data Ingestion 数据失败"));
          setData(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadDataIngestion();

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
