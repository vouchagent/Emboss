import { Footer, Layout, Navbar } from "nextra-theme-docs";
import { Head, Search } from "nextra/components";
import { getPageMap } from "nextra/page-map";
import "nextra-theme-docs/style.css";

export const metadata = {
  title: {
    default: "Emboss",
    template: "%s | Emboss",
  },
  description: "Emboss: precision PDF generation for Python",
};

const navbar = (
  <Navbar
    logo={<strong>Emboss</strong>}
    projectLink="https://github.com/GGChamp85/Emboss"
  />
);

const footer = <Footer>Apache-2.0</Footer>;

export default async function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head />
      <body>
        <Layout
          navbar={navbar}
          pageMap={await getPageMap()}
          footer={footer}
          search={<Search />}
          docsRepositoryBase="https://github.com/GGChamp85/Emboss/tree/main/docs"
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
