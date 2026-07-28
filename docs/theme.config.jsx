export default {
  logo: <strong>Emboss</strong>,
  project: {
    link: "https://github.com/GGChamp85/Emboss",
  },
  docsRepositoryBase: "https://github.com/GGChamp85/Emboss/tree/main/docs",
  footer: {
    text: "Apache-2.0",
  },
  useNextSeoProps() {
    return { titleTemplate: "%s | Emboss" };
  },
  head: (
    <>
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta
        name="description"
        content="Emboss: precision PDF generation for Python"
      />
    </>
  ),
};
