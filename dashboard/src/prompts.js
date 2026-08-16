const sharedInstructions = `Write a brief, natural enquiry in British English. Keep the body under 90 words, excluding the greeting and signature.
The sender is Kasper Pettersson, moving from Sweden to Oxford to begin a full-time MSc in Statistical Science at the University of Oxford.
Personalisation is optional. If used, write one simple, general sentence of no more than 15 words.
Good style: “The home looks comfortable, and the garden appeals to us.” or “The home looks cosy, and the location suits us well.”
Do not repeat or list several flattering details. Never paraphrase room layouts or chain advert features together. Never write phrases such as “particularly caught our attention”, “keen to make this our home”, or repeat the listing title.
The examples are tone references only. The shorter rules above override their length and wording.
Ask whether the accommodation is still available. Do not invent dates, employment, viewing availability, or other circumstances.
Begin with “Hi,” and use two short body paragraphs. Return only regular plain text without Markdown, headings, bullets, commentary, a subject line, or quotation marks.
End every message exactly with:
Best regards,
Kasper Pettersson`;
export const couplesPrompt = `${sharedInstructions}\n\nIntroduce the sender and clearly say that their partner will move in with them. Express interest simply, without overselling.`;

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
