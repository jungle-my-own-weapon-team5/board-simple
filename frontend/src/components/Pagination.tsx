import { Button } from "./ui/button";

type PaginationProps = {
  page: number;
  size: number;
  total: number;
  onPageChange: (page: number) => void;
};

export default function Pagination({ page, size, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / size));

  return (
    <div className="flex items-center justify-center gap-3">
      <Button type="button" variant="outline" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        이전
      </Button>
      <span className="text-sm font-semibold">
        {page} / {totalPages}
      </span>
      <Button
        type="button"
        variant="outline"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        다음
      </Button>
    </div>
  );
}
