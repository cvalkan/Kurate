export default function PrivacyPage() {
  return (
    <div className="container mx-auto px-4 max-w-3xl py-10">
      <h1 className="text-2xl font-bold mb-6">Privacy Policy</h1>
      <p className="text-sm text-muted-foreground mb-8">Last updated: May 22, 2026</p>

      <div className="prose prose-sm dark:prose-invert max-w-none space-y-6 text-sm leading-relaxed">
        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">1. Controller</h2>
          <p>
            Robert Lauko<br />
            c/o F2BII E-Commerce#660<br />
            Hintergoldingerstrasse 30<br />
            8638 Goldingen, Switzerland<br />
            Email: <a href="mailto:robert@kurate.org" className="text-accent hover:underline">robert@kurate.org</a>
          </p>
          <p className="mt-2">
            This privacy policy explains how Kurate.org ("we", "us", "the Service") collects, uses, and protects personal data
            in accordance with the Swiss Federal Act on Data Protection (nDSG/DSG, in force since 1 September 2023) and,
            where applicable, the EU General Data Protection Regulation (GDPR).
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">2. What Data We Collect</h2>
          <h3 className="font-medium mt-4 mb-2">2.1 Account Data (via Google Sign-In)</h3>
          <p>
            When you sign in using Google OAuth 2.0, we receive and store your <strong>name</strong>, <strong>email address</strong>,
            and <strong>Google account identifier</strong>. We do not receive or store your Google password. This data is used
            solely to authenticate your identity and personalize your experience (e.g., bookmarks, reading lists).
          </p>

          <h3 className="font-medium mt-4 mb-2">2.2 Usage Data (Google Analytics)</h3>
          <p>
            We use Google Analytics 4 (GA4) to understand how visitors use the Service. GA4 collects:
          </p>
          <ul className="list-disc ml-5 space-y-1">
            <li>IP address (anonymized by default in GA4)</li>
            <li>Browser type and version, operating system, screen resolution</li>
            <li>Pages visited, time spent, referral source</li>
            <li>Device type and approximate geographic location (country/region level)</li>
          </ul>
          <p className="mt-2">
            This data is transmitted to Google LLC servers in the United States.
            Google processes this data on our behalf under a data processing agreement.
            We have enabled IP anonymization and do not use GA4 for cross-site tracking or advertising.
          </p>

          <h3 className="font-medium mt-4 mb-2">2.3 Search Performance Data (Google Search Console)</h3>
          <p>
            We use Google Search Console to monitor how the Service appears in Google Search results.
            Google Search Console provides us with aggregated data about:
          </p>
          <ul className="list-disc ml-5 space-y-1">
            <li>Search queries that led users to the Service</li>
            <li>Click-through rates, impressions, and average ranking positions</li>
            <li>Crawl errors and indexing status of our pages</li>
          </ul>
          <p className="mt-2">
            This data is aggregated and does not contain personally identifiable information.
            It is processed by Google LLC under our Google Workspace account.
          </p>

          <h3 className="font-medium mt-4 mb-2">2.4 Server Logs</h3>
          <p>
            Our hosting infrastructure automatically logs HTTP requests, including IP addresses, request paths, timestamps,
            and user-agent strings. These logs are retained for up to 30 days for security and debugging purposes.
          </p>

          <h3 className="font-medium mt-4 mb-2">2.5 Cookies and Local Storage</h3>
          <p>
            We use essential cookies and browser local storage for authentication session management.
            Google Analytics sets its own cookies (<code>_ga</code>, <code>_ga_*</code>) for visitor identification across sessions.
            Reddit's advertising pixel sets a limited number of cookies (e.g. <code>_rdt_uuid</code>) used to measure
            advertising effectiveness (see section 2.5).
          </p>

          <h3 className="font-medium mt-4 mb-2">2.6 Reddit Advertising Pixel</h3>
          <p>
            We use the <strong>Reddit Pixel</strong> to measure the effectiveness of advertising campaigns we may
            run on reddit.com. The pixel fires a single <code>PageVisit</code> event when you load the site and
            transmits to Reddit Inc. (United States):
          </p>
          <ul className="list-disc ml-5 space-y-1">
            <li>Page URL and referrer</li>
            <li>IP address, browser user-agent, and a pseudonymous cookie identifier (<code>_rdt_uuid</code>)</li>
            <li>Approximate geographic location derived from IP</li>
          </ul>
          <p className="mt-2">
            Reddit's "auto-advanced matching" feature, which would additionally collect email addresses and phone
            numbers shown in the DOM (hashed with SHA-256 client-side) to improve cross-device attribution, is
            <strong> disabled</strong> on our account. We do not transmit any hashed personal identifiers to Reddit.
          </p>
          <p className="mt-2">
            Reddit processes this data as an independent controller for its own analytics and advertising purposes.
            See <a href="https://redditinc.com/policies/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Reddit's Privacy Policy</a> for details. You can opt out of Reddit's
            advertising cookies via your browser's tracking-protection settings or Reddit's ad preferences.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">3. Purpose and Legal Basis</h2>
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 pr-4 font-medium">Purpose</th>
                <th className="text-left py-2 font-medium">Legal Basis (nDSG/GDPR)</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr><td className="py-2 pr-4">User authentication (Google Sign-In)</td><td className="py-2">Consent / Contract performance</td></tr>
              <tr><td className="py-2 pr-4">Personalization (bookmarks, reading lists)</td><td className="py-2">Contract performance</td></tr>
              <tr><td className="py-2 pr-4">Website analytics (Google Analytics)</td><td className="py-2">Legitimate interest / Consent</td></tr>
              <tr><td className="py-2 pr-4">Search performance monitoring (Google Search Console)</td><td className="py-2">Legitimate interest</td></tr>
              <tr><td className="py-2 pr-4">Advertising measurement (Reddit Pixel)</td><td className="py-2">Legitimate interest / Consent</td></tr>
              <tr><td className="py-2 pr-4">Security and abuse prevention</td><td className="py-2">Legitimate interest</td></tr>
              <tr><td className="py-2 pr-4">Email notifications (if opted in)</td><td className="py-2">Consent</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">4. Data Transfers Abroad</h2>
          <p>
            Personal data may be transferred to the United States through our use of:
          </p>
          <ul className="list-disc ml-5 space-y-1">
            <li><strong>Google Analytics 4</strong> — analytics data processed by Google LLC, USA</li>
            <li><strong>Google Search Console</strong> — aggregated search performance data processed by Google LLC, USA</li>
            <li><strong>Google OAuth</strong> — authentication data processed by Google LLC, USA</li>
            <li><strong>Reddit Pixel</strong> — advertising measurement data processed by Reddit Inc., USA</li>
            <li><strong>Cloudflare</strong> — CDN and security services, data may transit through global servers</li>
          </ul>
          <p className="mt-2">
            The United States does not provide an equivalent level of data protection under Swiss law.
            These transfers are based on standard contractual clauses (SCCs) and the providers' compliance
            with applicable data protection frameworks. By using the Service, you acknowledge this transfer.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">5. Data Retention</h2>
          <ul className="list-disc ml-5 space-y-1">
            <li><strong>Account data</strong>: retained as long as your account is active. Deleted within 30 days of account deletion request.</li>
            <li><strong>Analytics data</strong>: retained for 14 months (GA4 default), then automatically deleted.</li>
            <li><strong>Server logs</strong>: retained for up to 30 days.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">6. Your Rights</h2>
          <p>Under the nDSG (and GDPR where applicable), you have the right to:</p>
          <ul className="list-disc ml-5 space-y-1">
            <li><strong>Access</strong> — request a copy of the personal data we hold about you</li>
            <li><strong>Rectification</strong> — correct inaccurate data</li>
            <li><strong>Deletion</strong> — request deletion of your data ("right to be forgotten")</li>
            <li><strong>Data portability</strong> — receive your data in a structured, machine-readable format</li>
            <li><strong>Object</strong> — object to processing based on legitimate interest</li>
            <li><strong>Withdraw consent</strong> — where processing is based on consent, withdraw it at any time</li>
          </ul>
          <p className="mt-2">
            To exercise any of these rights, contact us at{" "}
            <a href="mailto:privacy@kurate.org" className="text-accent hover:underline">privacy@kurate.org</a>.
            We will respond within 30 days.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">7. Data Security</h2>
          <p>
            We implement appropriate technical and organizational measures to protect personal data,
            including encrypted data transmission (TLS/HTTPS), access controls, and regular security reviews.
            However, no method of transmission over the Internet is 100% secure.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">8. Third-Party Services</h2>
          <ul className="list-disc ml-5 space-y-2">
            <li><strong>Google LLC</strong> (Google Sign-In, Google Analytics, Google Search Console) — <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Privacy Policy</a></li>
            <li><strong>Cloudflare Inc.</strong> (CDN, DDoS protection) — <a href="https://www.cloudflare.com/privacypolicy/" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Privacy Policy</a></li>
            <li><strong>MongoDB Inc.</strong> (database hosting) — <a href="https://www.mongodb.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Privacy Policy</a></li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">9. Children</h2>
          <p>
            The Service is not directed at children under 16. We do not knowingly collect personal data
            from children. If you believe a child has provided us with personal data, please contact us.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">10. Supervisory Authority</h2>
          <p>
            If you believe your data protection rights have been violated, you have the right to lodge a complaint with the:
          </p>
          <p className="mt-2">
            Federal Data Protection and Information Commissioner (FDPIC)<br />
            Feldeggweg 1<br />
            3003 Bern, Switzerland<br />
            <a href="https://www.edoeb.admin.ch" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">www.edoeb.admin.ch</a>
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold mt-8 mb-3">11. Changes to This Policy</h2>
          <p>
            We may update this privacy policy from time to time. Changes will be posted on this page
            with an updated "Last updated" date. We encourage you to review this policy periodically.
          </p>
        </section>
      </div>
    </div>
  );
}
