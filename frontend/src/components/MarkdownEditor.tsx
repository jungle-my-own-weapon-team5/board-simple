import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

type MarkdownEditorProps = {
  value: string;
  onChange: (value: string) => void;
};

export default function MarkdownEditor({ value, onChange }: MarkdownEditorProps) {
  return (
    <div className="editor-grid">
      <label className="field editor-pane">
        <span>Markdown</span>
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={14}
          placeholder="Markdown으로 내용을 작성하세요. #태그명 형식으로 태그를 추가할 수 있습니다."
        />
      </label>
      <section className="editor-pane preview-pane" aria-label="Markdown preview">
        <span className="field-label">Preview</span>
        <div className="markdown-body">
          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{value}</ReactMarkdown>
        </div>
      </section>
    </div>
  );
}
