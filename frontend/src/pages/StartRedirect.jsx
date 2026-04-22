import { Navigate, useLocation } from "react-router-dom";

/**
 * Google Ads campaign landing route.
 * Immediately forwards visitors from /start → / while preserving every query
 * parameter (utm_source, utm_medium, utm_campaign, gclid, …) so GA4 / Google
 * Ads attribution continues to work cleanly at the destination.
 */
export default function StartRedirect() {
  const location = useLocation();
  return (
    <Navigate
      to={{ pathname: "/", search: location.search, hash: location.hash }}
      replace
    />
  );
}
