const sharedInstructions = `Write one concise, natural enquiry message in British English.
Use only facts supplied in the current listing. Personalise the message specifically from its heading and description.
The examples are style references only: do not copy their wording or carry over property-specific details, because every listing differs.
Ask whether the accommodation is still available. Do not invent personal details, names, employment, dates, or viewing availability.
Return only the finished message as regular plain text. Do not use Markdown, headings, bullet points, commentary, a subject line, or quotation marks.`;

export const couplesPrompt = `${sharedInstructions}\n\nIntroduce the sender and clearly explain that their partner will move in with them. Express genuine interest in the accommodation.`;

export const selfContainedPrompt = `${sharedInstructions}\n\nIntroduce the sender and express genuine interest in the accommodation. Do not mention a partner or couple.`;

export const couplesExamples = [`Hi,

I’m very interested in the en-suite room. I’ll be moving from Sweden to Oxford to begin a full-time MSc in Statistical Science at the University of Oxford, and my partner would be staying with me as well.

We are a quiet, tidy and responsible couple, and the newly renovated property sounds like a very good fit for us.

Could you please let me know a little more about the room, including the rent, bills, availability and location? If possible, I’d also appreciate some photos.

As we are currently overseas, would an online/video viewing be possible?

Best regards,
Kasper Pettersson`];

export const selfContainedExamples = [`Hi,

I’m very interested in the furnished studio in Kidlington. I’ll be moving from Sweden to Oxford to begin a full-time MSc in Statistical Science at the University of Oxford.

I’m a quiet, tidy and responsible tenant, and I’m looking for a well-kept place to stay during my studies. The studio looks like a very good fit, especially with the bills included.

I’d be very interested to hear more about the property and the next steps for arranging a viewing or application.

Best regards,
Kaspar Pettersson`];
