import { useState } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { X, Lightbulb, MessageSquare } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export function SuggestionModal({ open, onClose, defaultType = "field" }) {
  const [type, setType] = useState(defaultType);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await axios.post(`${API}/api/suggestions`, { type, text }, { withCredentials: true });
      toast.success(type === "field" ? "Field suggestion submitted!" : "Feedback submitted!");
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
          <h2 className="text-base font-semibold">
            {type === "field" ? "Suggest a Field" : "Send Feedback"}
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div className="flex gap-2">
            <button
              onClick={() => setType("field")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${type === "field" ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground hover:text-foreground"}`}
              data-testid="suggestion-type-field"
            >
              <Lightbulb className="h-3 w-3" />
              Suggest Field
            </button>
            <button
              onClick={() => setType("general")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${type === "general" ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground hover:text-foreground"}`}
              data-testid="suggestion-type-general"
            >
              <MessageSquare className="h-3 w-3" />
              General Feedback
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            <Textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder={type === "field"
                ? "e.g., 'Add Machine Learning (cs.ML) — it would be great to see ML papers ranked...'"
                : "Share your thoughts, bug reports, or feature ideas..."
              }
              rows={4}
              className="text-sm"
              required
              data-testid="suggestion-text"
            />
            <p className="text-[10px] text-muted-foreground">
              {type === "field"
                ? "Suggest an arXiv category you'd like to see tracked. Include the category ID if you know it."
                : "Your feedback helps us improve PaperSumo."
              }
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
