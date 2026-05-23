import { useState } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { X, Lightbulb } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export function SuggestionModal({ open, onClose }) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await axios.post(`${API}/api/suggestions`, { type: "field", text }, { withCredentials: true });
      toast.success("Field suggestion submitted!");
      setText("");
      onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose} data-testid="suggestion-modal">
      <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <Lightbulb className="h-4 w-4" /> Suggest a Field
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4">
          <form onSubmit={handleSubmit} className="space-y-3">
            <Textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="e.g., 'Add Machine Learning (cs.ML) — it would be great to see ML papers ranked...'"
              rows={4}
              className="text-sm"
              required
              data-testid="suggestion-text"
            />
            <p className="text-[10px] text-muted-foreground">
              Suggest an arXiv category you'd like to see tracked. Include the category ID if you know it.
            </p>
            <Button type="submit" className="w-full" disabled={submitting || !text.trim()} data-testid="suggestion-submit">
              {submitting ? "Submitting..." : "Submit"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
