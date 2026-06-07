import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const HOMEPAGE_API = `${BACKEND_URL}/api/homepage`;

export const fieldAccent = {
  ai: { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200", dot: "bg-indigo-500" },
  cs: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", dot: "bg-blue-500" },
  robotics: { bg: "bg-teal-50", text: "text-teal-700", border: "border-teal-200", dot: "bg-teal-500" },
  quantum: { bg: "bg-cyan-50", text: "text-cyan-700", border: "border-cyan-200", dot: "bg-cyan-500" },
  math: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  biology: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
  econ: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },
  security: { bg: "bg-slate-100", text: "text-slate-700", border: "border-slate-300", dot: "bg-slate-500" },
};

export const accentFor = (field) => fieldAccent[field] || fieldAccent.cs;

export const homepageApi = {
  categories: () => axios.get(`${HOMEPAGE_API}/categories`).then((r) => r.data),
  metrics: () => axios.get(`${HOMEPAGE_API}/metrics`).then((r) => r.data),
  recent: () => axios.get(`${HOMEPAGE_API}/recent`).then((r) => r.data),
  papers: (params) => axios.get(`${HOMEPAGE_API}/papers`, { params }).then((r) => r.data),
};

export const RANK_TYPES = [
  { value: "score", label: "Score" },
  { value: "ai_rating", label: "Rating" },
  { value: "gap_score", label: "Gap" },
];

export const PERIODS = [
  { value: "all", label: "All Time" },
  { value: "recent", label: "Newly Added" },
  { value: "week", label: "Last 7 Days" },
  { value: "month", label: "Last 30 Days" },
];
