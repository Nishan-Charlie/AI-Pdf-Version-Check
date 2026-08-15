import type { Metadata } from "next";
import { Archivo, DM_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";

/*
  Three faces, three jobs.

  Archivo is a grotesque with the squared, slightly industrial build of signage
  and safety notices — it sets the interface and its headings. Source Serif 4
  was drawn for reading on screen and sets the clause text, so the panes read
  as the statute they quote rather than as interface. DM Mono carries anything
  that is an identifier rather than prose: clause numbers, similarity scores,
  jurisdiction codes.

  The split matters more than the names: chrome and document should not look
  like the same material, or a reader stops being able to tell the regulation
  from the tool reading it.
*/

const display = Archivo({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

const body = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  variable: "--font-body",
  display: "swap",
});

const mono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Regulation Diff — Fire Safety Standards",
  description:
    "Clause-level comparison of fire safety regulations across editions and jurisdictions.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${mono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
