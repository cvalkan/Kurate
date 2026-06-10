import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const HOMEPAGE_API = `${BACKEND_URL}/api/homepage`;

export const homepageApi = {
  categories: () => axios.get(`${HOMEPAGE_API}/categories`).then((r) => r.data),
  metrics: () => axios.get(`${HOMEPAGE_API}/metrics`).then((r) => r.data),
  recent: () => axios.get(`${HOMEPAGE_API}/recent`).then((r) => r.data),
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
