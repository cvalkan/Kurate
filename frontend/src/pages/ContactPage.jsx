import { useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Send, ArrowLeft, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ContactPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim() || !email.trim()) return;
    setSubmitting(true);
    try {
      await axios.post(`${API}/api/contact`, { name, email, message, website });
      setSubmitted(true);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to send. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-lg mx-auto px-4 py-16">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-8">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Kurate
        </Link>

        {submitted ? (
          <div className="text-center py-12" data-testid="contact-success">
            <CheckCircle2 className="h-12 w-12 text-emerald-500 mx-auto mb-4" />
            <h1 className="text-2xl font-semibold mb-2">Message sent</h1>
            <p className="text-muted-foreground">Thanks for reaching out. We'll get back to you soon.</p>
            <Link to="/">
              <Button variant="outline" className="mt-6">Back to Kurate</Button>
            </Link>
          </div>
        ) : (
          <>
            <h1 className="text-2xl font-semibold mb-1">Contact us</h1>
            <p className="text-muted-foreground mb-8">
              Questions, partnership inquiries, or bug reports — we'd love to hear from you.
            </p>

            <form onSubmit={handleSubmit} className="space-y-4" data-testid="contact-form">
              <div>
                <label className="text-sm font-medium mb-1.5 block">Name</label>
                <Input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Your name"
                  data-testid="contact-name"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1.5 block">Email <span className="text-red-500">*</span></label>
                <Input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@university.edu"
                  required
                  data-testid="contact-email"
                />
              </div>
              {/* Honeypot — hidden from humans, filled by bots */}
              <div className="absolute opacity-0 h-0 overflow-hidden" aria-hidden="true" tabIndex={-1}>
                <label>Website</label>
                <input
                  type="text"
                  value={website}
                  onChange={e => setWebsite(e.target.value)}
                  tabIndex={-1}
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1.5 block">Message <span className="text-red-500">*</span></label>
                <Textarea
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  placeholder="How can we help?"
                  rows={5}
                  required
                  data-testid="contact-message"
                />
              </div>
              <Button type="submit" className="w-full gap-2" disabled={submitting || !message.trim() || !email.trim()} data-testid="contact-submit">
                {submitting ? "Sending..." : <><Send className="h-3.5 w-3.5" /> Send message</>}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
